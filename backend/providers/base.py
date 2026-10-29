from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
import re
from pydantic import BaseModel

def mask_api_key(text: str, key: Optional[str]) -> str:
    """Safely masks any occurrence of the API key in error or output messages."""
    if not key or not text:
        return text
    clean_key = key.strip()
    if len(clean_key) <= 6:
        return text.replace(clean_key, "***")
    masked = clean_key[:3] + "..." + clean_key[-3:]
    return text.replace(clean_key, masked)

def mask_all_keys(text: str) -> str:
    """Masks potential API keys using regex heuristics."""
    # Matches common AI Studio / Google keys (AIzaSy...)
    text = re.sub(r'AIza[0-9A-Za-z-_]{30,45}', 'AIzaSy...***', text)
    # Matches standard Bearer tokens or sk- tokens
    text = re.sub(r'sk-[0-9A-Za-z-_]{20,55}', 'sk-...***', text)
    # Matches generic query param key=...
    text = re.sub(r'([?&]key=)[^&\s]+', r'\1***', text)
    return text

class LLMProvider(ABC):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key.strip() if api_key else ""
        self.model = model.strip() if model else ""

    @abstractmethod
    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Calls the provider with structured JSON output and returns the parsed JSON dict."""
        pass

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """Tests that the API key and model work with a minimal query."""
        pass
