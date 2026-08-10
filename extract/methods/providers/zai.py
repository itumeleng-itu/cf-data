"""Z.ai (GLM) provider -- same OpenAI-compatible chat-completions shape as
OpenRouter (see openrouter.py), with one addition: GLM-4.5V's extended
thinking mode, enabled via a top-level "thinking" key in the request body.
"""

import requests

from . import RateLimitError

_ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"
_DEFAULT_TIMEOUT = 180.0


class ZAIProvider:
    name = "zai"

    def __init__(self, api_key: str, model: str, http_post=None, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.api_key = api_key
        self.model = model
        self.http_post = http_post or requests.post
        self.timeout = timeout

    def complete(self, image_b64: str, page_text: str, prompt: str) -> str:
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": page_text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            },
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "thinking": {"type": "enabled"},
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = self.http_post(_ZAI_URL, headers=headers, json=payload, timeout=self.timeout)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            raise RateLimitError(retry_after=float(retry_after) if retry_after else None)

        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
