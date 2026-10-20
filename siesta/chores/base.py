"""Shared plumbing for chores."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import parse_json_lenient


@dataclass
class ChoreContext:
    """Everything a chore needs: the model backend, the store, the config."""

    backend: Any
    store: Any
    config: Any
    receipt: Any = None  # callable to log model calls to the cost ledger
    # Set by call_structured: did the picture actually reach the model?
    saw_image: bool = True


@dataclass
class ChoreResult:
    """What a chore produced."""

    kind: str
    ok: bool = True
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    # True when the agent should spend reasoning-model tokens on this result.
    needs_reasoning: bool = False
    reasoning_prompt: str = ""
    files: list[str] = field(default_factory=list)
    tokens: int = 0
    latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ok": self.ok,
            "summary": self.summary,
            "data": self.data,
            "needs_reasoning": self.needs_reasoning,
            "files": self.files,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


class BaseChore:
    """Interface every chore implements."""

    kind = "base"
    # Chores that only need the cheap path never call the reasoning model.
    needs_reasoning = False

    def detect(self, path: Path, config: Any = None) -> tuple[float, str]:
        """Return (confidence, reason) from metadata alone. 0 means "no idea"."""
        return 0.0, "no metadata signal"

    def run(self, path: Path, ctx: ChoreContext) -> ChoreResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Helpers shared by vision chores
# --------------------------------------------------------------------------- #
def encode_image(path: Path) -> str:
    """Base64-encode an image for the Ollama vision API."""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image_message(prompt: str, images: list[str]) -> list[dict[str, Any]]:
    """Build a chat message list for the native Ollama API.

    Ollama's ``/api/chat`` expects ``content`` to be a plain string; the
    images travel separately in the request's ``images`` array. The
    OpenAI-compatible endpoint accepts an array of content parts, but the
    native one does not, so keep it simple here.
    """
    return [{"role": "user", "content": prompt}]


def call_structured(
    ctx: ChoreContext,
    *,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    images: list[str] | None = None,
    temperature: float = 0.0,
    num_predict: int | None = None,
    phase: str = "extract",
    chore: str = "",
    num_ctx: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Call a model and parse its JSON-schema-constrained reply.

    Returns (parsed_object_or_None, receipt_dict).
    """
    messages = image_message(prompt, images or []) if images else [{"role": "user", "content": prompt}]
    response = ctx.backend.chat(
        model,
        messages,
        images=images,
        json_schema=schema,
        temperature=temperature,
        num_predict=num_predict,
        num_ctx=num_ctx,
    )
    receipt = response.as_receipt()
    if ctx.receipt:
        ctx.receipt(
            phase=phase,
            model=response.model,
            backend=getattr(ctx.backend, "name", "?"),
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            eval_tokens=response.eval_tokens,
            chore=chore,
        )
    parsed = parse_json_lenient(response.text)
    receipt["saw_image"] = True
    if images and hasattr(response, "saw_the_image"):
        # If the picture never reached the model, whatever came back is the
        # model improvising from the prompt. Say so rather than storing it.
        receipt["saw_image"] = response.saw_the_image()
        ctx.saw_image = receipt["saw_image"]
    if not isinstance(parsed, dict):
        return None, receipt
    return parsed, receipt
