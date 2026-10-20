"""Tidy chore — the folder you keep meaning to sort.

The agent proposes moves; it does not touch your files unless you ask it to.
Dry-run by default is not timidity, it is the only sane default for a tool
that moves files on a disk you care about.

Destinations are constrained to inside the watched folder, and every move is
checked for path traversal before it happens.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..prompts import TIDY_PROMPT, TIDY_SCHEMA
from ..util import DOCUMENT_SUFFIXES, supported
from .base import BaseChore, ChoreContext, ChoreResult, call_structured

ALLOWED_FOLDERS = {"receipts", "invoices", "photos", "notes", "archive"}


class TidyChore(BaseChore):
    kind = "tidy"
    needs_reasoning = False

    def detect(self, path: Path, config: Any = None) -> tuple[float, str]:
        parent = path.parent.name.lower()
        if parent in {"downloads", "to-sort", "unsorted", "to sort"}:
            return 0.72, "file is sitting in a to-sort folder"
        if config is not None:
            try:
                root = Path(config.watch_dir).resolve()
                if path.resolve().parent == root:
                    # A loose document in the inbox is probably clutter; a loose
                    # photo might be anything, so it needs a real decision.
                    if path.suffix.lower() in DOCUMENT_SUFFIXES:
                        return 0.7, "a loose document in the inbox"
                    return 0.4, "a loose file in the inbox"
            except OSError:
                pass
        return 0.0, "no signal"

    # ------------------------------------------------------------------ #
    def run(self, path: Path, ctx: ChoreContext) -> ChoreResult:
        watch = Path(ctx.config.watch_dir).resolve()
        # The trigger file is part of what needs sorting, so it stays in the
        # listing; everything else already inside a destination folder is left
        # alone.
        files = [p for p in sorted(watch.rglob("*")) if p.is_file() and supported(p)]
        if not files:
            return ChoreResult(
                kind=self.kind,
                ok=True,
                summary="Nothing to sort.",
                data={"moves": [], "applied": False},
                files=[str(path)],
            )

        listing = "\n".join(str(p.relative_to(watch)) for p in files[:60])
        parsed, receipt = call_structured(
            ctx,
            model=ctx.config.text_model,
            prompt=f"{TIDY_PROMPT}\nFILES (relative to the watched folder):\n{listing}",
            schema=TIDY_SCHEMA,
            phase="reason",
            chore=self.kind,
            num_predict=ctx.config.reason_budget,
        )
        if not parsed:
            return ChoreResult(
                kind=self.kind,
                ok=False,
                summary="Could not work out where these go.",
                error="text model returned no usable structure",
                tokens=receipt.get("total_tokens", 0),
                latency_ms=receipt.get("latency_ms", 0),
                files=[str(path)],
            )

        moves = []
        applied: list[str] = []
        skipped: list[str] = []
        for move in parsed.get("moves") or []:
            src = (watch / str(move.get("from", ""))).resolve()
            dst = (watch / str(move.get("to", ""))).resolve()
            # Safety: never move anything outside the watched folder, and never
            # follow a path that escapes it.
            if not str(src).startswith(str(watch)) or not str(dst).startswith(str(watch)):
                skipped.append(f"{move.get('from')} (outside the watched folder)")
                continue
            if not src.exists():
                skipped.append(f"{move.get('from')} (not found)")
                continue
            top = dst.relative_to(watch).parts[0] if dst.relative_to(watch).parts else ""
            if top and top.lower() not in ALLOWED_FOLDERS:
                skipped.append(f"{move.get('from')} -> {move.get('to')} (unknown folder)")
                continue
            moves.append({"from": str(src), "to": str(dst), "reason": move.get("reason", "")})
            if ctx.config.apply_tidy:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                applied.append(f"{src.name} -> {dst.relative_to(watch)}")

        return ChoreResult(
            kind=self.kind,
            ok=True,
            summary=(
                f"{len(moves)} files to sort ({len(applied)} moved)."
                if ctx.config.apply_tidy
                else f"{len(moves)} files could be sorted."
            ),
            data={
                "moves": [
                    {"from": str(Path(m['from']).relative_to(watch)), "to": str(Path(m['to']).relative_to(watch)), "reason": m["reason"]}
                    for m in moves
                ],
                "applied": ctx.config.apply_tidy,
                "moved": applied,
                "skipped": skipped,
                "dry_run": not ctx.config.apply_tidy,
            },
            tokens=receipt.get("total_tokens", 0),
            latency_ms=receipt.get("latency_ms", 0),
            files=[str(path)],
        )
