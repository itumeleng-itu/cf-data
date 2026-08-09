"""Provider seam for Method C's vision model, so switching providers
costs nothing in extract/methods/vision.py. A provider's job is narrow:
turn (image, page text, prompt) into a raw completion string, using
whatever request/response shape its own API needs -- OpenAI-style
messages for OpenRouter, contents/parts for Google AI Studio. Everything
provider-agnostic (rate-limit delay, 429 backoff, JSON-parse retry,
abstention, stats) lives once in vision.py and must not be reimplemented
per provider.

RateLimitError is how a provider reports "you're being rate-limited"
without vision.py's retry loop needing to know each API's own response
shape for that condition -- a provider raises it (optionally carrying
retry_after, parsed from whatever header/field its own API uses), and
the generic retry loop in vision.py does the rest.
"""

from typing import Protocol


class RateLimitError(Exception):
    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__("rate limited")


class VisionProvider(Protocol):
    name: str
    model: str

    def complete(self, image_b64: str, page_text: str, prompt: str) -> str: ...
