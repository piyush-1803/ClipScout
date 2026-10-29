import asyncio
import json
import random
import re
from typing import Any, Dict, List, Optional
import httpx
from .base import LLMProvider, mask_api_key, mask_all_keys

# Global cache of verified working model per API key to eliminate redundant calls
_KEY_RESOLVED_MODEL: Dict[str, str] = {}
_FAILED_MODELS_PER_KEY: Dict[str, set] = {}

def _score_model_preference(model_id: str) -> int:
    """
    Ranks models by capability, speed, and rock-solid Google AI Studio availability.
    gemini-1.5-flash is universally available on 100% of accounts without 404 errors.
    """
    m = model_id.lower()
    if "1.5-flash" in m and "8b" not in m:
        return 100
    if "1.5-flash-latest" in m:
        return 98
    if "2.0-flash" in m and "exp" not in m:
        return 90
    if "2.0-flash-exp" in m:
        return 85
    if "1.5-flash-8b" in m:
        return 80
    if "2.5-flash" in m:
        return 75
    if "1.5-pro" in m:
        return 70
    if "2.0-pro" in m:
        return 65
    if "flash" in m:
        return 60
    if "gemini" in m:
        return 50
    return 10

class GeminiProvider(LLMProvider):
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model: str = "auto"):
        clean_model = (model or "").removeprefix("models/").strip()
        if not clean_model:
            clean_model = "auto"
        super().__init__(api_key, clean_model)

    def _clean_json_text(self, text: str) -> str:
        """Strips markdown code fences, headers, and extracts the outermost JSON structure."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"```$", "", text, flags=re.MULTILINE).strip()
        
        # If wrapped by conversational preamble, locate the first { or [
        if not (text.startswith("{") or text.startswith("[")):
            match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
            if match:
                text = match.group(1).strip()
        return text

    async def auto_resolve_model(self, force_refresh: bool = False) -> str:
        """
        Queries Google AI Studio to discover models active for this specific key.
        Selects the best available model so the user never has to configure or guess model names.
        """
        if not self.api_key:
            return "gemini-1.5-flash"

        # Check cached resolution
        if not force_refresh and self.api_key in _KEY_RESOLVED_MODEL:
            return _KEY_RESOLVED_MODEL[self.api_key]

        failed_for_key = _FAILED_MODELS_PER_KEY.get(self.api_key, set())
        list_url = f"{self.BASE_URL}?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(list_url)
            
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("models", [])
                candidates = []
                for m in items:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        clean_name = m.get("name", "").removeprefix("models/").strip()
                        if clean_name not in failed_for_key:
                            candidates.append(clean_name)

                if candidates:
                    # If user chose a specific model and it exists and isn't blacklisted, honor it
                    if self.model and self.model not in ("auto", "default") and self.model in candidates:
                        _KEY_RESOLVED_MODEL[self.api_key] = self.model
                        return self.model

                    # Otherwise pick best ranked model for their account
                    candidates.sort(key=_score_model_preference, reverse=True)
                    chosen = candidates[0]
                    _KEY_RESOLVED_MODEL[self.api_key] = chosen
                    return chosen
        except Exception:
            pass

        fallback = "gemini-1.5-flash" if "gemini-1.5-flash" not in failed_for_key else "gemini-1.5-flash-8b"
        _KEY_RESOLVED_MODEL[self.api_key] = fallback
        return fallback

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Gemini API key is required.")

        # Resolve model if auto
        if self.model in ("auto", "default", ""):
            self.model = await self.auto_resolve_model()

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.3,
            }
        }

        if system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": system_prompt}]
            }

        max_retries = 4
        backoff = 3.0

        for attempt in range(max_retries):
            url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"}
                    )

                # Auto-heal on 404 (model not found on user's project/account)
                if resp.status_code == 404:
                    _FAILED_MODELS_PER_KEY.setdefault(self.api_key, set()).add(self.model)
                    new_model = await self.auto_resolve_model(force_refresh=True)
                    if new_model and new_model != self.model:
                        self.model = new_model
                        continue
                    else:
                        # Fallback directly to universal flash
                        self.model = "gemini-1.5-flash"
                        continue

                if resp.status_code == 429 or resp.status_code == 503:
                    # If repeated 429 on current model, try lightweight Flash-8B with independent quota
                    if attempt >= 1 and self.model != "gemini-1.5-flash-8b":
                        self.model = "gemini-1.5-flash-8b"
                        url = f"{self.BASE_URL}/{self.model}:generateContent?key={self.api_key}"

                    if attempt < max_retries - 1:
                        retry_after = resp.headers.get("Retry-After")
                        try:
                            sleep_time = float(retry_after) if retry_after else (backoff + random.uniform(0.5, 2.0))
                        except Exception:
                            sleep_time = backoff + random.uniform(0.5, 2.0)
                        sleep_time = min(sleep_time, 15.0)
                        await asyncio.sleep(sleep_time)
                        backoff *= 2.0
                        continue
                    else:
                        raise ValueError(
                            "Google Free-Tier rate limit reached (HTTP 429). The free quota refreshes every 30-60 seconds. "
                            "Please wait a moment or switch to Groq in Settings for unlimited fast calls."
                        )

                resp.raise_for_status()
                data = resp.json()

                candidates = data.get("candidates", [])
                if not candidates:
                    raise ValueError("Gemini returned empty response candidates.")

                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    raise ValueError("No content parts in Gemini response.")

                raw_text = parts[0].get("text", "")
                cleaned_text = self._clean_json_text(raw_text)

                try:
                    return json.loads(cleaned_text)
                except json.JSONDecodeError as jde:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0)
                        continue
                    raise ValueError(f"Failed to parse LLM JSON response: {jde}. Raw preview: {cleaned_text[:200]}")

            except httpx.HTTPStatusError as e:
                err_msg = e.response.text
                err_msg = mask_all_keys(mask_api_key(err_msg, self.api_key))
                status = e.response.status_code
                if status == 400:
                    raise ValueError(f"Gemini API Error (400 Bad Request): {err_msg}.")
                elif status == 403:
                    raise ValueError("Invalid Gemini API Key or permission denied (403). Check your key at Google AI Studio.")
                elif status == 404:
                    raise ValueError(f"Gemini model '{self.model}' not found (404).")
                elif status == 429:
                    raise ValueError("Gemini Free Tier rate limit exceeded (429). Please wait a moment and try again.")
                raise ValueError(f"Gemini API returned HTTP {status}: {err_msg}")
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5)
                    continue
                safe_err = mask_all_keys(mask_api_key(str(e), self.api_key))
                raise ValueError(f"Network error contacting Gemini API: {safe_err}")

        raise ValueError("Exceeded maximum retries calling Gemini.")

    async def _ping_model(self, target_model: str) -> Tuple[bool, str]:
        url = f"{self.BASE_URL}/{target_model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Say 'OK'."}]}],
            "generationConfig": {"maxOutputTokens": 10, "temperature": 0.0}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            if resp.status_code == 200:
                return True, "OK"
            elif resp.status_code == 404:
                return False, "404 Not Found"
            elif resp.status_code == 429:
                return False, "429 Rate Limit"
            elif resp.status_code == 403 or resp.status_code == 400:
                return False, f"HTTP {resp.status_code}"
            return False, f"HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    async def _verify_key_via_get(self) -> bool:
        """Verifies if the API key itself is authenticated by Google without consuming generation quota."""
        if not self.api_key:
            return False
        url = f"{self.BASE_URL}?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            return resp.status_code == 200
        except Exception:
            return False

    async def test_connection(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"success": False, "message": "Please enter an API key from Google AI Studio.", "model": self.model}

        # 1. If model is auto or empty, auto-detect right away
        target_model = self.model
        if target_model in ("auto", "default", ""):
            target_model = await self.auto_resolve_model(force_refresh=True)
            self.model = target_model

        # 2. Test ping with target model
        ok, reason = await self._ping_model(target_model)
        if ok:
            return {
                "success": True,
                "message": f"Connected! Active model '{target_model}' verified for your Google AI Studio key.",
                "model": target_model
            }

        # 3. If target_model failed with 404, auto-discover working models on this key
        if "404" in reason:
            auto_detected = await self.auto_resolve_model(force_refresh=True)
            if auto_detected and auto_detected != target_model:
                retry_ok, retry_reason = await self._ping_model(auto_detected)
                if retry_ok:
                    self.model = auto_detected
                    return {
                        "success": True,
                        "message": f"Connected! Auto-detected active model '{auto_detected}' for your Google AI Studio key.",
                        "model": auto_detected
                    }
                reason = retry_reason
                target_model = auto_detected

        # 4. If target model hit 429 (Rate limit / Quota), try alternative free-tier model (e.g. Flash-8B)
        if "429" in reason:
            alt_models = ["gemini-1.5-flash-8b", "gemini-1.5-flash", "gemini-2.0-flash-exp", "gemini-2.0-flash"]
            for alt in alt_models:
                if alt != target_model:
                    alt_ok, alt_reason = await self._ping_model(alt)
                    if alt_ok:
                        self.model = alt
                        return {
                            "success": True,
                            "message": f"Connected! Switched to '{alt}' to bypass rate limit.",
                            "model": alt
                        }

            # If all generation attempts hit 429, check if the key itself is valid via GET /models
            is_valid_key = await self._verify_key_via_get()
            if is_valid_key:
                return {
                    "success": False,
                    "message": "Key is valid! Google Free-Tier rate limit reached (HTTP 429). The quota resets every 30-60s. You can wait a moment, or switch to Groq (free, high-speed) in Settings.",
                    "model": target_model
                }

        # 5. Handle invalid key errors
        if "403" in reason or "400" in reason:
            return {
                "success": False,
                "message": "Invalid API key (403/400). Please copy a fresh key from https://aistudio.google.com/app/apikey",
                "model": self.model
            }

        return {
            "success": False,
            "message": f"Could not connect with key: {reason}. Google Free Tier limits may be active.",
            "model": self.model
        }

    async def list_available_models(self) -> List[Dict[str, str]]:
        """Queries Google Generative Language API in real-time to return models active for this key."""
        models: List[Dict[str, str]] = [
            {"id": "auto", "name": "✨ Auto (Detects Best Working Model on Your Key)"}
        ]

        if not self.api_key:
            models.extend(self._default_models())
            return models

        url = f"{self.BASE_URL}?key={self.api_key}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("models", [])
                detected = []
                for m in items:
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        clean_name = m.get("name", "").removeprefix("models/").strip()
                        display = m.get("displayName") or clean_name
                        detected.append({"id": clean_name, "name": display})
                if detected:
                    detected.sort(key=lambda x: _score_model_preference(x["id"]), reverse=True)
                    models.extend(detected)
                    return models
        except Exception:
            pass

        models.extend(self._default_models())
        return models

    def _default_models(self) -> List[Dict[str, str]]:
        return [
            {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash (Standard Free Tier)"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash"},
            {"id": "gemini-2.0-flash-exp", "name": "Gemini 2.0 Flash Experimental"},
            {"id": "gemini-1.5-flash-8b", "name": "Gemini 1.5 Flash-8B (Lightweight)"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro (Deep Reasoning)"},
        ]
