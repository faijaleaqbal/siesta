"""Receipt chore — a photo of a receipt becomes a row in a local expense log.

Small, cheap, and a good demonstration that a 3B vision model running on a
CPU can do real OCR well enough to be worth keeping. No receipt ever leaves
the machine, which is the whole selling point for anyone who does their own
books.

The chore is two-stage, and the split is not cosmetic:

  1. **Transcribe** (vision model): read the text off the paper, verbatim.
     A crumpled, skewed receipt is hard; *reading* it is much easier than
     *structuring* it.
  2. **Parse** (text model): turn that transcript into merchant, currency,
     total and line items, and do the arithmetic.

Asked for structured fields directly, the vision model returned a wrong
merchant, a wrong total and the wrong number of items. Asked only to
transcribe, and parsed by the text model, it gets it right.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..prompts import (
    RECEIPT_PARSE_PROMPT,
    RECEIPT_PARSE_SCHEMA,
    RECEIPT_TRANSCRIBE_PROMPT,
    RECEIPT_TRANSCRIBE_SCHEMA,
)
from .base import BaseChore, ChoreContext, ChoreResult, call_structured, encode_image


class ReceiptChore(BaseChore):
    kind = "receipt"
    needs_reasoning = False

    def detect(self, path: Path, config: Any = None) -> tuple[float, str]:
        name = path.name.lower()
        parent = path.parent.name.lower()
        if any(h in name for h in ("receipt", "bill", "invoice")):
            return 0.95, "filename says receipt"
        if any(h in parent for h in ("receipt", "bill", "invoice")):
            return 0.88, "folder says receipt"
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return 0.28, "photo, might be a receipt"
        return 0.0, "no signal"

    # ------------------------------------------------------------------ #
    def run(self, path: Path, ctx: ChoreContext) -> ChoreResult:
        images = [encode_image(path)]

        # Stage 1 — read the paper.
        transcript, receipt = call_structured(
            ctx,
            model=ctx.config.vision_model,
            prompt=RECEIPT_TRANSCRIBE_PROMPT,
            schema=RECEIPT_TRANSCRIBE_SCHEMA,
            images=images,
            phase="vision",
            chore=self.kind,
            num_predict=500,
        )
        lines = [str(line).strip() for line in ((transcript or {}).get("transcript") or "").splitlines()]
        lines = [line for line in lines if line]
        tokens = receipt.get("total_tokens", 0)
        latency = receipt.get("latency_ms", 0)

        if not lines:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="Could not read that receipt.",
                error="vision model returned no transcript",
                tokens=tokens,
                latency_ms=latency,
                files=[str(path)],
            )
        if not ctx.saw_image:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="The vision model never received the receipt.",
                error="the image did not reach the model - check `siesta doctor`",
                tokens=tokens,
                latency_ms=latency,
                files=[str(path)],
            )

        # Stage 2 — structure it.
        parsed, receipt = call_structured(
            ctx,
            model=ctx.config.text_model,
            prompt=RECEIPT_PARSE_PROMPT + "\n".join(lines),
            schema=RECEIPT_PARSE_SCHEMA,
            phase="enrich",
            chore=self.kind,
            num_predict=ctx.config.reason_budget,
        )
        tokens += receipt.get("total_tokens", 0)
        latency += receipt.get("latency_ms", 0)

        if not parsed:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="Read the receipt but could not structure it.",
                error="text model returned no usable structure",
                tokens=tokens,
                latency_ms=latency,
                files=[str(path)],
            )

        item_lines = parsed.get("lines") or []
        merchant = str(parsed.get("merchant") or "Unknown merchant")
        total = float(parsed.get("total") or 0.0)
        currency = str(parsed.get("currency") or "USD")

        # Cross-check: does the printed total match the sum of the lines?
        summed = sum(float(line.get("price") or 0.0) for line in item_lines)
        discrepancy = round(total - summed, 2)
        consistent = abs(discrepancy) <= 0.05 or not item_lines

        ctx.store.add_expense(
            merchant=merchant, total=total, currency=currency, lines=item_lines, source=str(path)
        )

        note = ""
        if not consistent:
            note = f"printed total {total:.2f} but the lines add up to {summed:.2f}"

        return ChoreResult(
            kind=self.kind,
            ok=True,
            summary=f"{merchant}: {total:.2f} {currency} over {len(item_lines)} items"
            + (f" ({note})" if note else ""),
            data={
                "merchant": merchant,
                "total": total,
                "currency": currency,
                "lines": item_lines,
                "lines_sum": round(summed, 2),
                "total_confirmed": bool(parsed.get("total_confirmed")),
                "consistent": consistent,
                "transcript": lines,
                "note": note,
            },
            tokens=tokens,
            latency_ms=latency,
            files=[str(path)],
        )
