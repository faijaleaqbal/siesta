"""The Siesta agent.

One pass of the agent looks like this::

    discover ──▶ (nothing new?) ──▶ sleep. no tokens. no notification.
        │
        ▼
     route ──▶ metadata? ──▶ chore ──┐
        │                             │
        │        not sure? ──▶ escalate│
        │                             ▼
        └──────────────────▶ compose one digest ──▶ write to disk

Two design rules drive everything here:

1. **Never speak twice.** If the last digest already said this, Siesta stays
   quiet. The comparison is semantic (embeddings), not string equality, so a
   re-photographed fridge does not generate a second identical digest.
2. **Spend the big model last.** The reasoning model is only reached when
   the cheap stages are unsure, and the digest is written once for the whole
   batch instead of once per file.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backends import build_backend
from .chores import ChoreContext, ChoreResult, get_chore
from .config import Config
from .digest import Digest, DigestSection, fallback_digest
from .energy import nap_decision
from .prompts import DIGEST_PROMPT, DIGEST_SCHEMA, PLAN_PROMPT, PLAN_SCHEMA
from .router import Router
from .store import Store
from .util import (
    atomic_write_text,
    cosine,
    file_fingerprint,
    is_image,
    now_iso,
    parse_json_lenient,
    sha256_file,
    stamp,
    supported,
    truncate,
)

log = logging.getLogger("siesta.agent")

# Semantic duplicate threshold for digests.
DIGEST_SIMILARITY = 0.965


@dataclass
class RunReport:
    """The result of one agent pass."""

    slept: bool = False
    reason: str = ""
    files_scanned: int = 0
    files_new: int = 0
    files_skipped: int = 0
    routes: list[dict[str, Any]] = field(default_factory=list)
    results: list[ChoreResult] = field(default_factory=list)
    digest: Digest | None = None
    digest_path: str | None = None
    duplicate: bool = False
    tokens: int = 0
    latency_ms: int = 0
    elapsed_ms: int = 0
    escalated: int = 0
    routed_by_metadata: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "slept": self.slept,
            "reason": self.reason,
            "files_scanned": self.files_scanned,
            "files_new": self.files_new,
            "files_skipped": self.files_skipped,
            "routes": self.routes,
            "results": [r.to_dict() for r in self.results],
            "digest_path": self.digest_path,
            "duplicate": self.duplicate,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "elapsed_ms": self.elapsed_ms,
            "escalated": self.escalated,
            "routed_by_metadata": self.routed_by_metadata,
        }

    def headline(self) -> str:
        if self.slept:
            return f"Still napping — {self.reason}"
        if self.duplicate:
            return "Nothing new to say — the last digest already covered this."
        return f"Handled {self.files_new} file(s): {', '.join(sorted({r.kind for r in self.results})) or 'nothing'}"


class Siesta:
    """The agent itself."""

    def __init__(
        self,
        config: Config | None = None,
        backend: Any = None,
        store: Store | None = None,
    ) -> None:
        self.config = config or Config.load()
        self.config.ensure_dirs()
        self.store = store or Store(self.config.db_path)
        self.backend = backend if backend is not None else build_backend(self.config)
        self.ctx = ChoreContext(
            backend=self.backend,
            store=self.store,
            config=self.config,
            receipt=self._receipt,
        )
        self.router = Router(self.ctx)

    # ------------------------------------------------------------------ #
    def _receipt(self, **kwargs: Any) -> None:
        """Log a model call to the cost ledger."""
        self.store.record_event(**kwargs)

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def _iter_files(self) -> list[Path]:
        root = Path(self.config.watch_dir)
        if not root.exists():
            return []
        found: list[Path] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            if not supported(path):
                continue
            found.append(path)
        return found

    def discover(self) -> tuple[list[Path], list[Path], int]:
        """Return (new_files, touched_but_identical, scanned).

        A file is *new* when we have never seen it, or when its bytes changed.
        A file whose bytes are identical but whose mtime moved is not new —
        that is exactly the kind of noise that should not wake the agent.
        """
        new_files: list[Path] = []
        touched: list[Path] = []
        files = self._iter_files()
        for path in files:
            key = str(path)
            fingerprint = file_fingerprint(path)
            row = self.store.seen(key)
            if row and row["fingerprint"] == fingerprint:
                continue
            digest = sha256_file(path)
            if row and row["sha256"] == digest:
                # Same content, new timestamp — update and stay asleep.
                self.store.mark_seen(
                    key,
                    fingerprint=fingerprint,
                    sha256=digest,
                    size=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                    chore=row["chore"] or "",
                    digest_id=row["digest_id"],
                    skipped=True,
                )
                touched.append(path)
                continue
            new_files.append(path)
        return new_files, touched, len(files)

    # ------------------------------------------------------------------ #
    # Chores
    # ------------------------------------------------------------------ #
    def _run_chores(self, paths: list[Path], report: RunReport) -> list[ChoreResult]:
        results: list[ChoreResult] = []
        tidy_done = False

        for path in paths:
            decision = self.router.route(path)
            report.routes.append(
                {
                    "file": path.name,
                    "kind": decision.kind,
                    "confidence": round(decision.confidence, 3),
                    "reason": decision.reason,
                    "decided_by": decision.decided_by,
                    "escalated": decision.escalated,
                }
            )
            if decision.decided_by == "metadata":
                report.routed_by_metadata += 1
            if decision.escalated:
                report.escalated += 1

            if decision.kind == "ignore" or decision.confidence < self.config.escalate_threshold:
                self.store.mark_seen(
                    str(path),
                    fingerprint=file_fingerprint(path),
                    sha256=sha256_file(path),
                    size=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                    chore="ignored",
                    skipped=True,
                )
                continue

            chore = get_chore(decision.kind)
            if decision.kind == "tidy" and tidy_done:
                continue
            try:
                result = chore.run(path, self.ctx)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("chore %s failed on %s: %s", decision.kind, path, exc)
                result = ChoreResult(kind=decision.kind, ok=False, error=str(exc), files=[str(path)])
            results.append(result)
            if decision.kind == "tidy":
                tidy_done = True

        return results

    # ------------------------------------------------------------------ #
    # Reasoning
    # ------------------------------------------------------------------ #
    def _plan(self, results: list[ChoreResult], report: RunReport) -> list[str]:
        """Ask the reasoning model for the *minimum* set of next actions.

        Only invoked when there is genuinely something to decide — food going
        off, a shopping list that suddenly matters.
        """
        pantry = [r for r in results if r.kind == "pantry" and r.ok]
        if not pantry:
            return []
        use_first: list[str] = []
        shopping: list[str] = []
        for result in pantry:
            for item in (result.data.get("use_first") or []):
                use_first.append(f"{item.get('name')} ({item.get('expiry_days')}d left)")
            for entry in (result.data.get("shopping_list") or []):
                shopping.append(str(entry.get("name")))
        if not use_first:
            return []

        notes = f"USE SOON: {', '.join(use_first)}\nMISSING STAPLES: {', '.join(shopping[:12])}"
        try:
            response = self.backend.chat(
                self.config.text_model,
                [{"role": "user", "content": f"{PLAN_PROMPT}\n{notes}"}],
                json_schema=PLAN_SCHEMA,
                temperature=0.0,
                num_predict=self.config.reason_budget,
            )
        except Exception:
            return []
        self._receipt(
            phase="plan",
            model=response.model,
            backend=getattr(self.backend, "name", "?"),
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            eval_tokens=response.eval_tokens,
        )
        report.tokens += response.total_tokens
        report.latency_ms += response.latency_ms
        parsed = parse_json_lenient(response.text)
        if not isinstance(parsed, dict):
            return []
        steps = [str(s) for s in (parsed.get("steps") or [])][:4]
        return steps

    def _compose(self, results: list[ChoreResult], files: int, report: RunReport) -> Digest:
        """Write one calm digest for the whole batch."""
        notes: list[str] = []
        for result in results:
            if not result.ok:
                continue
            if result.kind == "pantry":
                data = result.data
                if data.get("use_first"):
                    notes.append(
                        "Kitchen: "
                        + ", ".join(
                            f"{i.get('name')} (about {i.get('expiry_days')} day(s) left)"
                            for i in data["use_first"]
                        )
                    )
                if data.get("shopping_list"):
                    notes.append(
                        "Missing staples: "
                        + ", ".join(str(s.get("name")) for s in data["shopping_list"][:12])
                    )
                if data.get("note"):
                    notes.append(f"Kitchen note: {data['note']}")
            elif result.kind == "receipt":
                data = result.data
                notes.append(
                    f"Spending: {data.get('merchant')} {data.get('total')} {data.get('currency')}"
                    f" across {len(data.get('lines') or [])} items."
                )
            elif result.kind == "chat":
                if result.data.get("summary"):
                    notes.append(f"Chat summary: {result.data['summary']}")
                for item in (result.data.get("action_items") or [])[:3]:
                    notes.append(f"From a chat: {item}")
            elif result.kind == "tidy":
                data = result.data
                if data.get("moves"):
                    notes.append(
                        "Files to sort: "
                        + "; ".join(f"{m.get('from')} -> {m.get('to')}" for m in data["moves"][:6])
                    )
                if data.get("moved"):
                    notes.append("Files moved: " + "; ".join(data["moved"][:6]))

        if not notes:
            return fallback_digest(results, files)

        try:
            response = self.backend.chat(
                self.config.text_model,
                [{"role": "user", "content": f"{DIGEST_PROMPT}\nNOTES:\n" + "\n".join(notes)}],
                json_schema=DIGEST_SCHEMA,
                temperature=0.2,
                num_predict=self.config.digest_budget,
            )
        except Exception:
            return fallback_digest(results, files)

        self._receipt(
            phase="digest",
            model=response.model,
            backend=getattr(self.backend, "name", "?"),
            latency_ms=response.latency_ms,
            prompt_tokens=response.prompt_tokens,
            eval_tokens=response.eval_tokens,
        )
        report.tokens += response.total_tokens
        report.latency_ms += response.latency_ms

        parsed = parse_json_lenient(response.text)
        if not isinstance(parsed, dict) or not parsed.get("sections"):
            return fallback_digest(results, files)

        sections = [
            DigestSection(
                title=str(s.get("title") or "Notes"),
                body=str(s.get("body") or ""),
            )
            for s in parsed.get("sections") or []
        ]
        digest = Digest(
            headline=str(parsed.get("headline") or "A quiet night."),
            sections=sections,
            closing=str(parsed.get("closing") or "Nothing else needs doing tonight."),
            files=files,
            chores=[r.kind for r in results],
            tokens=report.tokens,
            latency_ms=report.latency_ms,
        )
        return digest

    # ------------------------------------------------------------------ #
    # Duplicate suppression
    # ------------------------------------------------------------------ #
    def _is_duplicate(self, digest: Digest) -> bool:
        """Has the agent already said this?

        Compares embeddings of the digest text, so a re-photographed fridge
        or a re-phrased summary does not produce a second identical digest.

        The current embedding is always stored, including on the very first
        digest — otherwise there would be nothing to compare against the
        second time round.
        """
        text = "\n".join([digest.headline] + [s.title + " " + s.body for s in digest.sections])
        try:
            vectors = self.backend.embed(self.config.embed_model, [text])
        except Exception:
            return False
        if not vectors:
            return False
        current_vec = vectors[0].vector

        previous = self.store.get_state("last_digest_embedding")
        self.store.set_state("last_digest_embedding", {"text": text, "vector": current_vec})
        if not previous:
            return False
        previous_vec = previous.get("vector") or [] if isinstance(previous, dict) else []
        if not previous_vec:
            return False
        return cosine(current_vec, previous_vec) >= DIGEST_SIMILARITY

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run_once(self, force: bool = False) -> RunReport:
        """Run one pass of the agent."""
        started = time.perf_counter()
        report = RunReport()

        decision = nap_decision(self.config, force=force)
        if not decision.should_run:
            report.slept = True
            report.reason = decision.reason
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

        new_files, touched, scanned = self.discover()
        report.files_scanned = scanned
        report.files_new = len(new_files)
        report.files_skipped = len(touched)

        if not new_files:
            report.slept = True
            report.reason = (
                f"nothing changed since the last pass ({scanned} file(s) watched)"
                if scanned
                else "nothing to watch yet"
            )
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

        results = self._run_chores(new_files, report)
        for result in results:
            report.tokens += result.tokens
            report.latency_ms += result.latency_ms
        report.results = results

        if not results:
            report.slept = True
            report.reason = "nothing worth waking up for"
            for path in new_files:
                self.store.mark_seen(
                    str(path),
                    fingerprint=file_fingerprint(path),
                    sha256=sha256_file(path),
                    size=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                    chore="ignored",
                    skipped=True,
                )
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

        steps = self._plan(results, report)
        digest = self._compose(results, len(new_files), report)

        if steps:
            digest.sections.append(DigestSection(title="If you feel like it", body="", bullets=steps))

        if self._is_duplicate(digest):
            report.duplicate = True
            report.reason = "already covered by the last digest"
            for path in new_files:
                self.store.mark_seen(
                    str(path),
                    fingerprint=file_fingerprint(path),
                    sha256=sha256_file(path),
                    size=path.stat().st_size,
                    mtime=path.stat().st_mtime,
                    chore="duplicate",
                    skipped=True,
                )
            report.digest = digest
            report.elapsed_ms = int((time.perf_counter() - started) * 1000)
            return report

        digest.tokens = report.tokens
        digest.latency_ms = report.latency_ms
        path = Path(self.config.digest_dir) / f"{stamp()}.md"
        atomic_write_text(path, digest.to_markdown())
        report.digest = digest
        report.digest_path = str(path)

        digest_id = self.store.add_digest(
            path=str(path),
            headline=digest.headline,
            markdown=digest.to_markdown(),
            files=len(new_files),
            items=len(self.store.list_items()),
            tokens=report.tokens,
        )
        for result in results:
            for file_path in result.files:
                p = Path(file_path)
                if not p.exists():
                    continue
                self.store.mark_seen(
                    file_path,
                    fingerprint=file_fingerprint(p),
                    sha256=sha256_file(p),
                    size=p.stat().st_size,
                    mtime=p.stat().st_mtime,
                    chore=result.kind,
                    digest_id=digest_id,
                )

        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report

    # ------------------------------------------------------------------ #
    def status(self) -> dict[str, Any]:
        """A snapshot for ``siesta status`` and the web UI."""
        totals = self.store.token_totals()
        return {
            "ts": now_iso(),
            "watch_dir": str(self.config.watch_dir),
            "backend": getattr(self.backend, "name", "?"),
            "backend_health": self.backend.health() if hasattr(self.backend, "health") else {},
            "files_watched": len(self._iter_files()),
            "files_processed": self.store.seen_count(),
            "items_in_pantry": len(self.store.list_items()),
            "expenses_total": round(self.store.expense_total(), 2),
            "last_digest": self.store.last_digest(),
            "tokens": totals,
            "chores": self.store.events_by_phase(),
        }
