"""Run Siesta end to end against the real local models and print a transcript.

This is the script that produced every number quoted in the README and the
DEV post. It needs a running Ollama with the three models installed:

    ollama pull qwen2.5vl:3b
    ollama pull qwen2.5:3b-instruct
    ollama pull nomic-embed-text
    python scripts/demo_real.py

It creates a scratch inbox with the two example photos and a chat
transcript, runs the agent, and then demonstrates the three behaviours that
matter: the agent sleeps when nothing changed, it sleeps when a file was
merely touched, and it wakes up when the content actually changed.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from siesta.agent import Siesta  # noqa: E402
from siesta.bench import format_summary, run_benchmark  # noqa: E402
from siesta.config import Config  # noqa: E402
from siesta.store import Store  # noqa: E402

CHAT = """Ana: Are we still on for Saturday?
Ben: Yes, 6pm at the usual place. I'll bring the projector.
Ana: Perfect. Can you also send the slides to Priya before then?
Ben: Will do. I need the final numbers from accounting first though.
Ana: Take your time, just don't forget about the projector adaptor.
"""


def banner(text: str) -> None:
    print("\n" + "=" * 74)
    print(text)
    print("=" * 74, flush=True)


def call_count(store: Store) -> int:
    return store.token_totals()["calls"]


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="siesta-demo-"))
    inbox = scratch / "inbox"
    for folder in ("fridge", "receipts", "chats"):
        (inbox / folder).mkdir(parents=True, exist_ok=True)

    examples = ROOT / "examples"
    if (examples / "fridge-photo.png").exists():
        shutil.copy2(examples / "fridge-photo.png", inbox / "fridge" / "fridge-photo.png")
    if (examples / "receipt-photo.png").exists():
        shutil.copy2(examples / "receipt-photo.png", inbox / "receipts" / "receipt-photo.png")
    (inbox / "chats" / "weekend-chat.txt").write_text(CHAT, encoding="utf-8")

    config = Config(
        home=scratch / "home",
        watch_dir=inbox,
        data_dir=scratch / "data",
        digest_dir=scratch / "digests",
        energy_aware=False,
    )
    config.ensure_dirs()
    store = Store(config.db_path)
    agent = Siesta(config=config, store=store)

    try:
        # ---------------------------------------------------------------- #
        banner("1. FIRST PASS - a fridge photo, a receipt and a chat transcript")
        start = time.time()
        report = agent.run_once(force=True)
        print(f"wall clock: {time.time() - start:.1f}s")
        print(report.headline())
        print()
        for route in report.routes:
            print(
                f"  route  {route['file']:<26} -> {route['kind']:<8} "
                f"({route['confidence']:.2f}, decided by {route['decided_by']})"
            )
        print()
        for result in report.results:
            print(f"  chore  {result.kind:<8} {result.summary}")
            if result.kind == "pantry":
                confirmed = [c["name"] for c in result.data.get("confirmed", [])]
                print(f"         confirmed: {', '.join(confirmed)}")
                uncertain = [c["name"] for c in result.data.get("uncertain", [])]
                if uncertain:
                    print(f"         set aside as uncertain: {', '.join(uncertain)}")
                print(f"         use first: {[i['name'] for i in result.data.get('use_first', [])]}")
                buy = [i["name"] for i in result.data.get("shopping_list", [])]
                print(f"         buy: {buy[:8]}")
            if result.kind == "receipt":
                print(f"         lines sum: {result.data.get('lines_sum')} vs printed "
                      f"{result.data.get('total')} -> {'consistent' if result.data.get('consistent') else 'MISMATCH'}")
        print()
        print(
            f"  {report.tokens} tokens - {report.latency_ms} ms of model time - "
            f"{report.routed_by_metadata}/{len(report.routes)} routed without a model"
        )

        if report.digest:
            banner("2. THE DIGEST IT LEFT")
            print(report.digest.to_markdown())

        # ---------------------------------------------------------------- #
        banner("3. SECOND PASS - nothing changed, so it should sleep")
        before = call_count(store)
        report2 = agent.run_once()
        print(f"  {report2.headline()}")
        print(f"  model calls made during this pass: {call_count(store) - before}")
        print(f"  reason: {report2.reason}")

        # ---------------------------------------------------------------- #
        banner("4. TOUCHING A FILE - same bytes, new timestamp")
        target = inbox / "chats" / "weekend-chat.txt"
        target.write_text(CHAT, encoding="utf-8")
        before = call_count(store)
        report3 = agent.run_once()
        print(f"  {report3.headline()}")
        print(f"  model calls made during this pass: {call_count(store) - before}")
        print(f"  reason: {report3.reason}")

        # ---------------------------------------------------------------- #
        banner("5. CHANGING A FILE - the agent should wake up")
        target.write_text(CHAT + "\nPriya: I cannot make Saturday, sorry.\n", encoding="utf-8")
        before = call_count(store)
        report4 = agent.run_once()
        print(f"  {report4.headline()}")
        print(f"  model calls made during this pass: {call_count(store) - before}")
        for result in report4.results:
            print(f"  chore  {result.kind:<8} {result.summary}")

        # ---------------------------------------------------------------- #
        banner("6. CASCADE BENCHMARK - naive pipeline vs the Nap Cascade")
        bench = run_benchmark(agent)
        print(format_summary(bench.summary()))
        print("\n  per-file routing:")
        for entry in bench.per_file:
            print(
                f"    {entry['file']:<26} {entry['kind']:<8} "
                f"({entry['confidence']:.2f}, {entry['decided_by']})"
            )

        # ---------------------------------------------------------------- #
        banner("7. THE COST LEDGER - every model call that was actually made")
        for row in store.events_by_phase():
            print(
                f"  {row['phase']:<8} {row['model']:<22} {row['calls']} call(s)  "
                f"{row['prompt_tokens'] + row['eval_tokens']:>6} tok  {row['latency_ms']:>6} ms"
            )
        totals = store.token_totals()
        print(f"  TOTAL   {totals['calls']} call(s)  {totals['total_tokens']} tokens  {totals['latency_ms']} ms")
        print("\n  pantry now holds:")
        for item in store.list_items():
            print(
                f"    {item['name']:<18} x{item['quantity']} {item['unit']:<8} "
                f"{item['category']:<10} {item['condition']:<8} {item['expiry_days']}d"
            )
        print(f"\n  expenses: {store.expense_total():.2f} across {len(store.list_expenses())} receipt(s)")
    finally:
        store.close()
        shutil.rmtree(scratch, ignore_errors=True)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
