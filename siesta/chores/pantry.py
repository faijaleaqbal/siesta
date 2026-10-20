"""Pantry chore — photo of the fridge becomes a shopping list.

This is the chore that makes the "open model" argument concrete: recognising
that a tub in the photo is yoghurt and not milk is a *vision* problem, and
solving it on a laptop with no API key is the whole point of the project.

The chore runs in three steps, and the split is not cosmetic — it is what
stopped the model from inventing food:

  1. **Scan** (vision model): enumerate the objects that are genuinely
     visible, shelf by shelf, each with a confidence. Short output, so it
     is also fast on a CPU.
  2. **Filter**: anything below the confidence threshold is set aside as
     *uncertain* rather than silently dropped or silently trusted.
  3. **Enrich** (text model): fill in category, quantity, condition and
     expiry for the confirmed names only. This is a cheap text-only call
     working from names the vision model already confirmed, so it cannot
     introduce an item that is not in the picture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..prompts import PANTRY_ENRICH_PROMPT, PANTRY_ENRICH_SCHEMA, PANTRY_SCAN_PROMPT, PANTRY_SCAN_SCHEMA
from ..util import same_item
from .base import BaseChore, ChoreContext, ChoreResult, call_structured, encode_image

# A deliberately short list. A long one produces a shopping list nobody reads.
STAPLES: list[tuple[str, str]] = [
    ("milk", "dairy"),
    ("eggs", "protein"),
    ("bread", "grain"),
    ("butter", "dairy"),
    ("cheese", "dairy"),
    ("yogurt", "dairy"),
    ("rice", "grain"),
    ("pasta", "grain"),
    ("onions", "vegetable"),
    ("garlic", "vegetable"),
    ("potatoes", "vegetable"),
    ("tomatoes", "vegetable"),
    ("olive oil", "condiment"),
    ("salt", "condiment"),
    ("sugar", "condiment"),
    ("coffee", "beverage"),
]

# Items at or above this confidence are treated as seen.
CONFIDENT_AT = 0.55


class PantryChore(BaseChore):
    kind = "pantry"
    needs_reasoning = False

    # ------------------------------------------------------------------ #
    def detect(self, path: Path, config: Any = None) -> tuple[float, str]:
        name = path.name.lower()
        parent = path.parent.name.lower()
        hints = ("fridge", "pantry", "kitchen", "grocer", "larder")
        if any(h in name or h in parent for h in hints):
            return 0.93, "filename or folder mentions a fridge/pantry"
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            return 0.34, "looks like a photo, could be anything"
        return 0.0, "no signal"

    # ------------------------------------------------------------------ #
    def _scan(self, path: Path, ctx: ChoreContext) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Stage 1+2: look, then keep only what the model is confident about."""
        images = [encode_image(path)]
        parsed, receipt = call_structured(
            ctx,
            model=ctx.config.vision_model,
            prompt=PANTRY_SCAN_PROMPT,
            schema=PANTRY_SCAN_SCHEMA,
            images=images,
            phase="vision",
            chore=self.kind,
            num_predict=400,
        )
        objects = (parsed or {}).get("objects") or []

        confirmed: list[dict[str, Any]] = []
        uncertain: list[dict[str, Any]] = []
        for item in objects:
            name = str(item.get("name", "")).strip().lower()
            if not name:
                continue
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            entry = {"name": name, "shelf": str(item.get("shelf", "")), "confidence": confidence}
            if confidence >= CONFIDENT_AT:
                confirmed.append(entry)
            else:
                uncertain.append(entry)

        # The same object listed twice is one object.
        deduped: list[dict[str, Any]] = []
        for entry in confirmed:
            if not any(entry["name"] in other["name"] or other["name"] in entry["name"] for other in deduped):
                deduped.append(entry)

        return deduped, uncertain, receipt.get("total_tokens", 0)

    # ------------------------------------------------------------------ #
    def _enrich(self, confirmed: list[dict[str, Any]], ctx: ChoreContext) -> tuple[dict[str, Any], int]:
        """Stage 3: the cheap text model fills in the details."""
        if not confirmed:
            return {}, 0
        listing = "\n".join(f"- {item['name']}" for item in confirmed)
        parsed, receipt = call_structured(
            ctx,
            model=ctx.config.text_model,
            prompt=PANTRY_ENRICH_PROMPT + listing,
            schema=PANTRY_ENRICH_SCHEMA,
            phase="enrich",
            chore=self.kind,
            num_predict=ctx.config.reason_budget,
        )
        return parsed or {}, receipt.get("total_tokens", 0)

    # ------------------------------------------------------------------ #
    def run(self, path: Path, ctx: ChoreContext) -> ChoreResult:
        confirmed, uncertain, scan_tokens = self._scan(path, ctx)
        if not confirmed and not uncertain:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="Could not read that photo.",
                error="vision model returned no usable structure",
                tokens=scan_tokens,
                files=[str(path)],
            )
        if not ctx.saw_image:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="The vision model never received the photo.",
                error="the image did not reach the model - check `siesta doctor`",
                tokens=scan_tokens,
                files=[str(path)],
            )

        details, enrich_tokens = self._enrich(confirmed, ctx)
        by_name = {
            str(item.get("name", "")).strip().lower(): item
            for item in (details.get("items") or [])
        }

        tokens = scan_tokens + enrich_tokens
        saved = 0
        for entry in confirmed:
            name = entry["name"]
            detail = by_name.get(name, {})
            expiry_days = detail.get("expiry_days")
            expiry_days = int(expiry_days) if isinstance(expiry_days, (int, float)) and expiry_days >= 0 else None
            ctx.store.upsert_item(
                name=name,
                raw_name=name,
                category=str(detail.get("category") or "unknown"),
                quantity=float(detail.get("quantity") or 0),
                unit=str(detail.get("unit") or ""),
                condition=str(detail.get("condition") or "unknown"),
                expiry_days=expiry_days,
                source=str(path),
                confidence=entry.get("confidence", 0.0),
            )
            saved += 1

        inventory = ctx.store.list_items()
        use_first = [
            i for i in inventory if i.get("expiry_days") is not None and int(i["expiry_days"]) <= 3
        ]
        # "milk carton" is milk. Without this, a fridge full of milk makes
        # the agent tell you to buy milk.
        in_stock = [i["name"] for i in inventory if float(i.get("quantity") or 0) > 0]
        buy = [
            {"name": staple, "category": category}
            for staple, category in STAPLES
            if not any(same_item(staple, have) for have in in_stock)
        ]
        # Staples that already need using come first.
        buy.sort(key=lambda s: 0 if any(same_item(s["name"], i["name"]) for i in use_first) else 1)

        ctx.store.set_state("shopping_list", buy)
        ctx.store.set_state("use_first", [{"name": i["name"], "expiry_days": i["expiry_days"]} for i in use_first])
        ctx.store.set_state("uncertain_items", uncertain)

        summary_bits = []
        if use_first:
            summary_bits.append("Use soon: " + ", ".join(i["name"] for i in use_first[:3]))
        if buy:
            summary_bits.append(f"{len(buy)} staples missing")
        else:
            summary_bits.append("Pantry looks complete")
        if uncertain:
            summary_bits.append(f"{len(uncertain)} uncertain item(s) set aside")

        return ChoreResult(
            kind=self.kind,
            ok=True,
            summary="; ".join(summary_bits),
            data={
                "items_seen": len(confirmed),
                "items_saved": saved,
                "confirmed": confirmed,
                "uncertain": uncertain,
                "use_first": [
                    {"name": i["name"], "expiry_days": i["expiry_days"], "category": i.get("category")}
                    for i in use_first
                ],
                "shopping_list": buy,
            },
            tokens=tokens,
            files=[str(path)],
        )
