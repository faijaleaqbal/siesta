"""Chat chore — "what did I miss?" in two lines.

Two input shapes:

* a **screenshot** of a chat app — read by the open-weight vision model,
* an **exported chat file** (.txt transcript, .json export) — read directly,
  no vision model needed at all.

Either way the summary is written by the open-weight *text* model, which is
the one call in this chore that actually needs language understanding.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..prompts import CHAT_PROMPT, CHAT_SCHEMA, SUMMARY_PROMPT, SUMMARY_SCHEMA
from ..util import read_text_safe, truncate
from .base import BaseChore, ChoreContext, ChoreResult, call_structured, encode_image


class ChatChore(BaseChore):
    kind = "chat"
    needs_reasoning = True

    def detect(self, path: Path, config: Any = None) -> tuple[float, str]:
        name = path.name.lower()
        parent = path.parent.name.lower()
        if any(h in name for h in ("chat", "whatsapp", "telegram", "slack", "discord", "dm")):
            return 0.95, "filename says chat"
        if any(h in parent for h in ("chat", "whatsapp", "telegram", "messages")):
            return 0.9, "folder says chat"
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return 0.3, "photo, could be a chat screenshot"
        return 0.0, "no signal"

    # ------------------------------------------------------------------ #
    def _transcript_text(self, path: Path) -> str:
        """Pull messages out of a .txt or .json chat export."""
        raw = read_text_safe(path)
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return truncate(raw, 6000)
            if isinstance(data, dict):
                for key in ("messages", "chats", "conversation", "data"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if isinstance(data, list):
                lines = []
                for entry in data:
                    if isinstance(entry, dict):
                        who = entry.get("sender") or entry.get("author") or entry.get("from") or "?"
                        body = entry.get("text") or entry.get("message") or entry.get("body") or ""
                        lines.append(f"{who}: {body}")
                    else:
                        lines.append(str(entry))
                return truncate("\n".join(lines), 6000)
            return truncate(str(data), 6000)
        return truncate(raw, 6000)

    # ------------------------------------------------------------------ #
    def run(self, path: Path, ctx: ChoreContext) -> ChoreResult:
        tokens = 0
        latency = 0
        transcript = ""
        messages: list[dict[str, Any]] = []
        participants: list[str] = []

        if path.suffix.lower() in {".txt", ".json", ".md"}:
            # Free path: no vision model at all.
            transcript = self._transcript_text(path)
        else:
            parsed, receipt = call_structured(
                ctx,
                model=ctx.config.vision_model,
                prompt=CHAT_PROMPT,
                schema=CHAT_SCHEMA,
                images=[encode_image(path)],
                phase="vision",
                chore=self.kind,
            )
            tokens += receipt.get("total_tokens", 0)
            latency += receipt.get("latency_ms", 0)
            if parsed:
                messages = parsed.get("messages") or []
                participants = parsed.get("participants") or []
                transcript = "\n".join(
                    f"{m.get('speaker', '?')}: {m.get('text', '')}" for m in messages
                )

        if not transcript.strip():
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="Nothing readable in that chat.",
                error="no transcript produced",
                tokens=tokens,
                latency_ms=latency,
                files=[str(path)],
            )

        # The reasoning step: two lines, written by the text model.
        summary_payload, receipt = call_structured(
            ctx,
            model=ctx.config.text_model,
            prompt=f"{SUMMARY_PROMPT}\n\nCONVERSATION:\n{transcript}",
            schema=SUMMARY_SCHEMA,
            phase="reason",
            chore=self.kind,
            num_predict=ctx.config.reason_budget,
        )
        tokens += receipt.get("total_tokens", 0)
        latency += receipt.get("latency_ms", 0)

        summary = ""
        action_items: list[str] = []
        if summary_payload:
            summary = str(summary_payload.get("summary") or "")
            action_items = [str(a) for a in (summary_payload.get("action_items") or [])]

        return ChoreResult(
            kind=self.kind,
            ok=bool(summary),
            summary=summary or "Could not summarise that conversation.",
            data={
                "summary": summary,
                "action_items": action_items,
                "participants": participants,
                "message_count": len(messages),
                "transcript_preview": truncate(transcript, 600),
            },
            tokens=tokens,
            latency_ms=latency,
            files=[str(path)],
        )
