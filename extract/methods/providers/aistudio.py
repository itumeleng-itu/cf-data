"""Google AI Studio (Gemini) provider -- no routing intermediary, so none
of OpenRouter's guardrail/data-policy gate applies. Confirmed directly
against the live API before writing the parsing code (not guessed):
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
with header x-goog-api-key, body {"contents": [{"parts": [...]}],
"generationConfig": {...}}, and the completion text at
response["candidates"][0]["content"]["parts"][0]["text"] -- verified
with both a text-only call and one carrying an inline_data image part
(the latter correctly described the real UJ page content back, not a
generic non-answer, confirming the model can actually see the image).

Default model is gemini-2.5-flash: queried the account's live model list
(GET /v1beta/models) rather than assuming a slug exists, and picked the
established non-preview flash tier -- large context, free-tier eligible,
not one of the exotic/undocumented preview names also present in that
list (gemini-3.6-flash, antigravity-preview-05-2026, etc.).
"""

import requests

from . import RateLimitError

_AISTUDIO_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_DEFAULT_TIMEOUT = 180.0


class AIStudioProvider:
    name = "aistudio"

    def __init__(self, api_key: str, model: str, http_post=None, timeout: float = _DEFAULT_TIMEOUT) -> None:
        self.api_key = api_key
        self.model = model
        self.http_post = http_post or requests.post
        self.timeout = timeout

    def complete(self, image_b64: str, page_text: str, prompt: str) -> str:
        url = _AISTUDIO_URL_TEMPLATE.format(model=self.model)
        body = {
            "contents": [{
                "parts": [
                    {"text": f"{prompt}\n\n{page_text}"},
                    {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                ],
            }],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        response = self.http_post(url, headers=headers, json=body, timeout=self.timeout)

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
            raise RateLimitError(retry_after=float(retry_after) if retry_after else None)

        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
