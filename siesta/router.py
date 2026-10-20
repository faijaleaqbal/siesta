"""The router — Siesta's cheap gate.

This is the heart of the cascade. Before any expensive model touches a file,
Siesta asks the cheapest question it can:

  1. **Metadata** (free, deterministic): does the filename or folder already
     tell us what this is? ``receipts/IMG_0042.jpg`` → receipt, no model calls.
  2. **Tiny vision model** (optional, ~250 MB): if a cheap VLM is installed,
     let it look at the image and pick a chore.
  3. **Reasoning model** (expensive): only when the first two are unsure.

Every route decision records which stage made the call, because that ratio is
the whole argument of the project: *how often did we get away without the
big model?*
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .chores import REGISTRY, get_chore
from .prompts import ROUTER_PROMPT, ROUTER_SCHEMA
from .util import parse_json_lenient, truncate


@dataclass
class RouteDecision:
    kind: str
    confidence: float
    reason: str
    decided_by: str  # metadata | gate_model | reason_model | fallback
    escalated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Router:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------------ #
    def _metadata_route(self, path: Path) -> RouteDecision:
        best = RouteDecision(kind="ignore", confidence=0.0, reason="no metadata signal", decided_by="metadata")
        for kind in REGISTRY:
            confidence, reason = get_chore(kind).detect(path, self.ctx.config)
            if confidence > best.confidence:
                best = RouteDecision(
                    kind=kind if confidence > 0 else "ignore",
                    confidence=confidence,
                    reason=reason,
                    decided_by="metadata",
                )
        return best

    # ------------------------------------------------------------------ #
    def _gate_model_route(self, path: Path) -> RouteDecision | None:
        model = getattr(self.ctx.config, "gate_model", "")
        if not model:
            return None
        try:
            from .chores.base import encode_image, image_message

            images = [encode_image(path)] if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else []
            messages = image_message(ROUTER_PROMPT, images)
            response = self.ctx.backend.chat(
                model, messages, images=images, json_schema=ROUTER_SCHEMA, temperature=0.0, num_predict=120
            )
        except Exception:
            return None
        if self.ctx.receipt:
            self.ctx.receipt(
                phase="gate",
                model=response.model,
                backend=getattr(self.ctx.backend, "name", "?"),
                latency_ms=response.latency_ms,
                prompt_tokens=response.prompt_tokens,
                eval_tokens=response.eval_tokens,
                note=str(path),
            )
        parsed = parse_json_lenient(response.text)
        if not isinstance(parsed, dict):
            return None
        kind = str(parsed.get("kind") or "ignore")
        if kind not in REGISTRY and kind != "ignore":
            kind = "ignore"
        return RouteDecision(
            kind=kind,
            confidence=float(parsed.get("confidence") or 0.0),
            reason=str(parsed.get("reason") or ""),
            decided_by="gate_model",
        )

    # ------------------------------------------------------------------ #
    def _reason_model_route(self, path: Path) -> RouteDecision:
        """Last resort: let the reasoning model decide, with the file attached."""
        try:
            from .chores.base import encode_image, image_message

            images = [encode_image(path)] if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else []
            context = f"\nFILE NAME: {path.name}\nFOLDER: {path.parent.name}\n"
            messages = image_message(ROUTER_PROMPT + context, images)
            response = self.ctx.backend.chat(
                self.ctx.config.text_model,
                messages,
                images=images,
                json_schema=ROUTER_SCHEMA,
                temperature=0.0,
                num_predict=160,
            )
        except Exception:
            return RouteDecision(
                kind="ignore", confidence=0.0, reason="routing failed", decided_by="fallback", escalated=True
            )
        if self.ctx.receipt:
            self.ctx.receipt(
                phase="route",
                model=response.model,
                backend=getattr(self.ctx.backend, "name", "?"),
                latency_ms=response.latency_ms,
                prompt_tokens=response.prompt_tokens,
                eval_tokens=response.eval_tokens,
                note=str(path),
            )
        parsed = parse_json_lenient(response.text)
        if not isinstance(parsed, dict):
            return RouteDecision(
                kind="ignore", confidence=0.0, reason="reasoner gave no structure", decided_by="fallback", escalated=True
            )
        kind = str(parsed.get("kind") or "ignore")
        if kind not in REGISTRY and kind != "ignore":
            kind = "ignore"
        return RouteDecision(
            kind=kind,
            confidence=float(parsed.get("confidence") or 0.0),
            reason=str(parsed.get("reason") or ""),
            decided_by="reason_model",
            escalated=True,
        )

    # ------------------------------------------------------------------ #
    def route(self, path: Path) -> RouteDecision:
        """Route one file to a chore, escalating only when necessary."""
        decision = self._metadata_route(path)
        if decision.confidence >= self.ctx.config.gate_threshold:
            return decision

        # Stage 2: cheap vision gate (only if the user installed one).
        gated = self._gate_model_route(path)
        if gated and gated.confidence >= self.ctx.config.escalate_threshold:
            return gated
        if gated and gated.confidence > decision.confidence:
            decision = gated

        # Stage 3: escalate to the reasoning model.
        escalated = self._reason_model_route(path)
        if escalated.confidence >= self.ctx.config.escalate_threshold:
            return escalated
        if escalated.confidence > decision.confidence:
            return escalated
        return decision


def describe_candidates(path: Path) -> str:
    """Human-readable summary of the metadata signals for one file."""
    lines = []
    for kind in REGISTRY:
        confidence, reason = get_chore(kind).detect(path, None)
        if confidence > 0:
            lines.append(f"  {kind}: {confidence:.2f} ({reason})")
    return "\n".join(lines) or "  (no signal)"


__all__ = ["Router", "RouteDecision", "describe_candidates", "truncate"]
