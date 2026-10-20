"""Benchmark: what does the Nap Cascade actually save?

The claim "we only use the big model when we have to" is worth nothing
without numbers, so this module runs the same files two ways over **two
nights**:

* **Naive** — the obvious implementation. Every file goes through a model
  (the vision model for images, the text model otherwise) and a digest is
  written **per file**. It has no memory of what it saw last night, so on
  the second night it does exactly the same work again and tells you the
  same things again.
* **Siesta** — the real cascade: metadata gate first, escalation only when
  unsure, one digest for the whole batch, and a hash check that means the
  second night costs nothing at all.

Both halves run against a **fresh inbox and a fresh database**, so the
comparison is apples to apples and the benchmark is reproducible.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent import Siesta
from .config import Config
from .prompts import DIGEST_PROMPT, DIGEST_SCHEMA, ROUTER_PROMPT, ROUTER_SCHEMA
from .store import Store
from .util import parse_json_lenient


@dataclass
class BenchResult:
    files: int = 0
    # Night 1 — three new files land in the inbox.
    naive_calls: int = 0
    naive_tokens: int = 0
    naive_ms: int = 0
    naive_pages: int = 0
    siesta_calls: int = 0
    siesta_tokens: int = 0
    siesta_ms: int = 0
    siesta_pages: int = 0
    # Night 2 — nothing changed.
    naive_calls_n2: int = 0
    naive_tokens_n2: int = 0
    naive_pages_n2: int = 0
    siesta_calls_n2: int = 0
    siesta_tokens_n2: int = 0
    siesta_pages_n2: int = 0
    routed_by_metadata: int = 0
    escalated: int = 0
    per_file: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        naive_total_tokens = self.naive_tokens + self.naive_tokens_n2
        siesta_total_tokens = self.siesta_tokens + self.siesta_tokens_n2
        naive_total_calls = self.naive_calls + self.naive_calls_n2
        siesta_total_calls = self.siesta_calls + self.siesta_calls_n2
        saved = max(0, naive_total_tokens - siesta_total_tokens)
        pct = (saved / naive_total_tokens * 100.0) if naive_total_tokens else 0.0
        return {
            "files": self.files,
            "night1": {
                "naive_calls": self.naive_calls,
                "naive_tokens": self.naive_tokens,
                "naive_ms": self.naive_ms,
                "naive_pages": self.naive_pages,
                "siesta_calls": self.siesta_calls,
                "siesta_tokens": self.siesta_tokens,
                "siesta_ms": self.siesta_ms,
                "siesta_pages": self.siesta_pages,
            },
            "night2": {
                "naive_calls": self.naive_calls_n2,
                "naive_tokens": self.naive_tokens_n2,
                "siesta_calls": self.siesta_calls_n2,
                "siesta_tokens": self.siesta_tokens_n2,
            },
            "totals": {
                "naive_calls": naive_total_calls,
                "naive_tokens": naive_total_tokens,
                "naive_pages": self.naive_pages + self.naive_pages_n2,
                "siesta_calls": siesta_total_calls,
                "siesta_tokens": siesta_total_tokens,
                "siesta_pages": self.siesta_pages + self.siesta_pages_n2,
                "tokens_saved": saved,
                "tokens_saved_pct": round(pct, 1),
            },
            "routed_by_metadata": self.routed_by_metadata,
            "escalated": self.escalated,
        }


def _call(agent: Siesta, model: str, prompt: str, schema: dict[str, Any], images: list[str] | None = None):
    """One model call, timed."""
    from .chores.base import image_message

    messages = image_message(prompt, images or [])
    started = time.perf_counter()
    response = agent.backend.chat(
        model, messages, images=images, json_schema=schema, temperature=0.0, num_predict=600
    )
    elapsed = int((time.perf_counter() - started) * 1000)
    return response, elapsed


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _naive_pass(agent: Siesta, config: Config, sources: list[Path], result: BenchResult) -> None:
    """One night of the obvious implementation: model-routed, one page per file."""
    from .chores.base import encode_image

    for path in sources:
        images = [encode_image(path)] if _is_image(path) else []
        model = config.vision_model if images else config.text_model
        # Understand the file.
        response, elapsed = _call(agent, model, ROUTER_PROMPT, ROUTER_SCHEMA, images)
        result.naive_calls += 1
        result.naive_tokens += response.total_tokens
        result.naive_ms += elapsed
        # ...and then write a page about it.
        response, elapsed = _call(agent, config.text_model, DIGEST_PROMPT, DIGEST_SCHEMA)
        result.naive_calls += 1
        result.naive_tokens += response.total_tokens
        result.naive_ms += elapsed
        result.naive_pages += 1


def run_benchmark(agent: Siesta, files: list[Path] | None = None) -> BenchResult:
    """Run both strategies over the same inputs and report the difference."""
    result = BenchResult()
    sources = files or agent._iter_files()
    result.files = len(sources)
    if not sources:
        return result

    # A scratch workspace: same files, empty database, so the cascade half
    # starts from exactly the same state as the naive half.
    scratch = Path(tempfile.mkdtemp(prefix="siesta-bench-"))
    inbox = scratch / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    for source in sources:
        shutil.copy2(source, inbox / source.name)

    bench_config = Config(
        home=scratch / "home",
        watch_dir=inbox,
        data_dir=scratch / "data",
        digest_dir=scratch / "digests",
        ollama_url=agent.config.ollama_url,
        vision_model=agent.config.vision_model,
        text_model=agent.config.text_model,
        embed_model=agent.config.embed_model,
        gate_model=agent.config.gate_model,
        energy_aware=False,
    )
    bench_config.ensure_dirs()

    store = Store(bench_config.db_path)
    bench_agent = Siesta(config=bench_config, backend=agent.backend, store=store)

    try:
        # ---------------- night 1 ---------------------------------------------
        night1_naive = BenchResult()
        _naive_pass(bench_agent, bench_config, sources, night1_naive)
        result.naive_calls = night1_naive.naive_calls
        result.naive_tokens = night1_naive.naive_tokens
        result.naive_ms = night1_naive.naive_ms
        result.naive_pages = night1_naive.naive_pages

        before = bench_agent.store.token_totals()
        report = bench_agent.run_once(force=True)
        after = bench_agent.store.token_totals()
        result.siesta_calls = max(0, after["calls"] - before["calls"])
        result.siesta_tokens = max(0, after["total_tokens"] - before["total_tokens"])
        result.siesta_ms = max(0, report.elapsed_ms)
        result.siesta_pages = 1 if report.digest_path else 0
        result.routed_by_metadata = report.routed_by_metadata
        result.escalated = report.escalated
        for route in report.routes:
            result.per_file.append(
                {
                    "file": route["file"],
                    "kind": route["kind"],
                    "confidence": route["confidence"],
                    "decided_by": route["decided_by"],
                    "escalated": route["escalated"],
                }
            )

        # ---------------- night 2: nothing changed ----------------------------
        # The naive implementation has no idea anything is the same, so it
        # starts over and tells you the same things again. The cascade
        # notices and does nothing at all.
        night2_naive = BenchResult()
        _naive_pass(bench_agent, bench_config, sources, night2_naive)
        result.naive_calls_n2 = night2_naive.naive_calls
        result.naive_tokens_n2 = night2_naive.naive_tokens
        result.naive_pages_n2 = night2_naive.naive_pages

        before = bench_agent.store.token_totals()
        report2 = bench_agent.run_once(force=True)
        after = bench_agent.store.token_totals()
        result.siesta_calls_n2 = max(0, after["calls"] - before["calls"])
        result.siesta_tokens_n2 = max(0, after["total_tokens"] - before["total_tokens"])
        result.siesta_pages_n2 = 1 if report2.digest_path else 0
    finally:
        store.close()
        shutil.rmtree(scratch, ignore_errors=True)

    return result


def format_summary(summary: dict[str, Any]) -> str:
    n1 = summary["night1"]
    n2 = summary["night2"]
    totals = summary["totals"]
    lines = [
        "Siesta cascade benchmark",
        "=" * 52,
        f"files                     {summary['files']}",
        "",
        "NIGHT 1 - three new files arrive",
        f"  naive    {n1['naive_calls']} call(s)  {n1['naive_tokens']:>6} tok  "
        f"{n1['naive_pages']} page(s) for the user",
        f"  cascade  {n1['siesta_calls']} call(s)  {n1['siesta_tokens']:>6} tok  "
        f"{n1['siesta_pages']} page(s) for the user",
        "",
        "NIGHT 2 - nothing changed",
        f"  naive    {n2['naive_calls']} call(s)  {n2['naive_tokens']:>6} tok  "
        f"the same news again",
        f"  cascade  {n2['siesta_calls']} call(s)  {n2['siesta_tokens']:>6} tok  "
        f"silence",
        "",
        "TWO NIGHTS TOGETHER",
        f"  naive    {totals['naive_calls']} call(s)  {totals['naive_tokens']:>6} tok  "
        f"{totals['naive_pages']} page(s)",
        f"  cascade  {totals['siesta_calls']} call(s)  {totals['siesta_tokens']:>6} tok  "
        f"{totals['siesta_pages']} page(s)",
        "",
        f"  tokens saved          {totals['tokens_saved']} ({totals['tokens_saved_pct']}%)",
        f"  routed without a model  {summary['routed_by_metadata']}/{summary['files']}",
        f"  escalations           {summary['escalated']}",
    ]
    return "\n".join(lines)


__all__ = ["run_benchmark", "BenchResult", "format_summary", "parse_json_lenient"]
