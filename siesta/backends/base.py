"""Backend interface.

A backend is anything that can answer three questions:

  1. chat(...)      — text + optional images in, text out
  2. embed(...)     — strings in, vectors out
  3. available()    — is it usable right now?

Everything Siesta knows about models lives behind this interface, which is why
swapping Qwen for Gemma or Llama is a config change and nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass
class ChatResponse:
    """Result of one model call, including the receipt for the cost ledger."""

    text: str
    model: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    eval_tokens: int = 0
    # Prompt tokens attributable to attached images. An image costs roughly a
    # thousand tokens; if this is zero the picture never reached the model.
    image_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.eval_tokens

    def saw_the_image(self, minimum: int = 400) -> bool:
        """True when the prompt was long enough to include an image."""
        return self.image_tokens >= minimum

    def as_receipt(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "eval_tokens": self.eval_tokens,
            "total_tokens": self.total_tokens,
            "image_tokens": self.image_tokens,
        }


@dataclass
class Embedding:
    vector: list[float]
    model: str = ""

    def __iter__(self):
        return iter(self.vector)


class Backend(Protocol):
    """Protocol implemented by :class:`OllamaBackend` and :class:`StubBackend`."""

    name: str

    def available(self) -> bool:
        """True when this backend can serve requests right now."""

    def health(self) -> dict[str, Any]:
        """Human-readable status, shown by ``siesta doctor`` and the web UI."""

    def chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        images: Sequence[str] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ) -> ChatResponse:
        """One chat completion. ``images`` are base64-encoded data URLs."""

    def embed(self, model: str, inputs: Sequence[str]) -> list[Embedding]:
        """Embed a batch of strings."""
