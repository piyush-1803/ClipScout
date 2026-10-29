import asyncio
import json
import random
import re
from typing import Any, Dict, Optional
import httpx
from .base import LLMProvider, mask_api_key, mask_all_keys

class OpenAICompatProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        super().__init__(api_key, model)
        self.base_url = (base_url or "https://api.groq.com/openai/v1").rstrip("/")
        if not self.model:
            self.model = "llama-3.3-70b-versatile"

    def _clean_json_text(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"```$", "", text, flags=re.MULTILINE).strip()
        return text

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        max_retries = 3
        backoff = 2.0

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 429 or resp.status_code == 503:
                    if attempt < max_retries - 1:
                        sleep_time = backoff + random.uniform(0.5, 1.5)
                        await asyncio.sleep(sleep_time)
                        backoff *= 2.0
                        continue
                    else:
                        resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()

                choices = data.get("choices", [])
                if not choices:
                    raise ValueError("OpenAI-compatible API returned no choices.")

                raw_text = choices[0].get("message", {}).get("content", "")
                cleaned_text = self._clean_json_text(raw_text)

                try:
                    return json.loads(cleaned_text)
                except json.JSONDecodeError as jde:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0)
                        continue
                    raise ValueError(f"Failed to parse LLM JSON response: {jde}. Raw text preview: {cleaned_text[:200]}")

            except httpx.HTTPStatusError as e:
                err_msg = e.response.text
                err_msg = mask_all_keys(mask_api_key(err_msg, self.api_key))
                status = e.response.status_code
                if status == 401 or status == 403:
                    raise ValueError("Invalid API key or unauthorized (401/403).")
                elif status == 404:
                    raise ValueError(f"Model or endpoint not found (404) at {self.base_url}.")
                elif status == 429:
                    raise ValueError("Rate limit exceeded on OpenAI-compatible provider (429).")
                raise ValueError(f"OpenAI-compatible provider returned HTTP {status}: {err_msg}")
            except httpx.RequestError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5)
                    continue
                safe_err = mask_all_keys(mask_api_key(str(e), self.api_key))
                raise ValueError(f"Network error contacting OpenAI-compatible provider: {safe_err}")

        raise ValueError("Exceeded maximum retries calling OpenAI-compatible provider.")

    async def test_connection(self) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Say 'OK'."}],
            "max_tokens": 10,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return {
                "success": True,
                "message": f"Successfully connected to {self.base_url} with model '{self.model}'.",
                "model": self.model,
            }
        except httpx.HTTPStatusError as e:
            err_msg = mask_all_keys(mask_api_key(e.response.text, self.api_key))
            status = e.response.status_code
            if status in (401, 403):
                msg = "Authentication failed (401/403). Please verify your API key."
            elif status == 404:
                msg = f"Model '{self.model}' or URL '{self.base_url}' not found (404)."
            elif status == 429:
                msg = "Rate limit reached (429)."
            else:
                msg = f"Error {status}: {err_msg}"
            return {"success": False, "message": msg, "model": self.model}
        except Exception as e:
            safe_err = mask_all_keys(mask_api_key(str(e), self.api_key))
            return {"success": False, "message": f"Connection failed: {safe_err}", "model": self.model}

    async def list_available_models(self) -> List[Dict[str, str]]:
        """Queries the provider's /models endpoint to return models active for this key."""
        if not self.api_key:
            return self._default_models()

        url = f"{self.base_url}/models"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data") or data.get("models") or []
                models = []
                for item in items:
                    mid = item.get("id") or item.get("name")
                    if mid:
                        models.append({"id": mid, "name": mid})
                if models:
                    return models
        except Exception:
            pass

        return self._default_models()

    def _default_models(self) -> List[Dict[str, str]]:
        return [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile (Groq)"},
            {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill 70B"},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B (32k)"},
            {"id": "gpt-4o", "name": "GPT-4o (OpenAI)"},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
        ]
