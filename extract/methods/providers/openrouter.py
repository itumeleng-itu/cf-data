"""OpenRouter provider -- the original Method C implementation, moved
here unchanged in behaviour. Kept, not deleted: it works, it's just
blocked on the account this project currently runs under (confirmed via
direct testing: a 404 "no endpoints available matching your guardrail
restrictions and data policy" persisted across every free model tried,
even for a plain text-only request with no image and no JSON mode, so
it's a full account-level routing gate, not a per-model or per-request
issue). If that's ever resolved, or a paid OpenRouter run is wanted
again, this provider is ready as-is -- just set VISION_PROVIDER=openrouter.
"""

import requests

from . import RateLimitError

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_TIMEOUT = 180.0


class OpenRouterProvider:
    name = "openrouter"

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
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = self.http_post(_OPENROUTER_URL, headers=headers, json=payload, timeout=self.timeout)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            raise RateLimitError(retry_after=float(retry_after) if retry_after else None)

        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
