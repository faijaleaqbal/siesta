"""Siesta command line interface.

    siesta init            create the local folders and config
    siesta scan            run one pass of the agent now
    siesta status          what has the agent been up to
    siesta watch           run the overnight loop
    siesta serve           start the local web UI
    siesta bench           measure what the cascade saves
    siesta doctor          check models, backend and folders
    siesta demo            run the whole pipeline on a generated sample
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import Siesta
from .backends import build_backend
from .config import Config
from .store import Store
from .util import setup_logging


# --------------------------------------------------------------------------- #
def _config_from_args(args: argparse.Namespace) -> Config:
    config = Config.load(getattr(args, "config", None))
    if getattr(args, "watch_dir", None):
        config.watch_dir = Path(args.watch_dir).expanduser()
    if getattr(args, "vision_model", None):
        config.vision_model = args.vision_model
    if getattr(args, "text_model", None):
        config.text_model = args.text_model
    if getattr(args, "embed_model", None):
        config.embed_model = args.embed_model
    if getattr(args, "ollama_url", None):
        config.ollama_url = args.ollama_url
    if getattr(args, "gate_model", None) is not None:
        config.gate_model = args.gate_model
    if getattr(args, "apply_tidy", False):
        config.apply_tidy = True
    if getattr(args, "idle_seconds", None) is not None:
        config.idle_seconds = args.idle_seconds
    if getattr(args, "energy_aware", False):
        config.energy_aware = True
    if getattr(args, "backend", None):
        config.backend_kind = args.backend
    return config


def _agent(args: argparse.Namespace) -> Siesta:
    config = _config_from_args(args)
    backend = build_backend(config, getattr(args, "backend", "auto"))
    return Siesta(config=config, backend=backend)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    config.ensure_dirs()
    path = config.save()
    print(f"Siesta is ready.")
    print(f"  config     {path}")
    print(f"  inbox      {config.watch_dir}")
    print(f"  data       {config.data_dir}")
    print(f"  digests    {config.digest_dir}")
    print()
    print("Drop a fridge photo, a receipt or a chat screenshot into the inbox,")
    print("then run:  siesta scan")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    agent = _agent(args)
    report = agent.run_once(force=args.force)
    print(report.headline())
    print(f"  {report.reason}" if report.reason else "")
    if report.routes:
        print("  routing:")
        for route in report.routes:
            flag = "escalated" if route["escalated"] else route["decided_by"]
            print(f"    {route['file']:<28} -> {route['kind']:<8} ({route['confidence']:.2f}, {flag})")
    if report.results:
        print("  chores:")
        for result in report.results:
            status = "ok " if result.ok else "err"
            print(f"    [{status}] {result.kind:<8} {result.summary}")
    if report.digest_path:
        print(f"  digest -> {report.digest_path}")
    print(
        f"  {report.tokens} tokens · {report.latency_ms} ms of model time · "
        f"{report.elapsed_ms} ms wall clock · {report.routed_by_metadata}/{len(report.routes)} routed without a model"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    agent = _agent(args)
    status = agent.status()
    print("Siesta status")
    print("-" * 40)
    print(f"  inbox        {status['watch_dir']}")
    print(f"  backend      {status['backend']}")
    health = status.get("backend_health") or {}
    if health.get("missing"):
        print(f"  missing      {', '.join(f'{k} ({v})' for k, v in health['missing'].items())}")
    print(f"  watched      {status['files_watched']} file(s)")
    print(f"  processed    {status['files_processed']} file(s)")
    print(f"  pantry       {status['items_in_pantry']} item(s)")
    print(f"  spending     {status['expenses_total']}")
    print(f"  tokens       {status['tokens']['total_tokens']} across {status['tokens']['calls']} call(s)")
    last = status.get("last_digest")
    if last:
        print(f"  last digest  {last['ts']} — {last['headline']}")
        print(f"               {last['path']}")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from .nap import Watcher

    agent = _agent(args)
    watcher = Watcher(agent, interval=args.interval)

    def show(report) -> None:
        marker = "nap" if report.slept else "work"
        print(f"[{marker}] {report.headline()}")

    watcher.on_report = show
    stats = watcher.run_forever()
    print(
        f"\n{stats.passes} pass(es), {stats.asleep_passes} asleep, "
        f"{stats.handled} with work, {stats.tokens} tokens"
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("The web UI needs two extra packages:\n\n    pip install fastapi uvicorn\n")
        return 1
    from .web import create_app

    config = _config_from_args(args)
    app = create_app(config)
    print(f"Siesta is serving on http://{args.host}:{args.port}")
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from .bench import format_summary, run_benchmark

    agent = _agent(args)
    result = run_benchmark(agent)
    summary = result.summary()
    print(format_summary(summary))
    out = Path(args.out) if args.out else Path("siesta-benchmark.json")
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwritten to {out}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    print("Siesta doctor")
    print("-" * 40)
    print(f"  python      {sys.version.split()[0]}")
    print(f"  inbox       {config.watch_dir} {'(exists)' if config.watch_dir.exists() else '(missing)'}")
    print(f"  data        {config.data_dir} {'(exists)' if config.data_dir.exists() else '(missing)'}")
    print(f"  db          {config.db_path} {'(exists)' if config.db_path.exists() else '(not created yet)'}")

    backend = build_backend(config, "ollama")
    health = backend.health()
    print(f"  ollama      {config.ollama_url} -> {'reachable' if health.get('reachable') else 'NOT reachable'}")
    if health.get("installed"):
        print(f"  models      {', '.join(health['installed'])}")
    if health.get("missing"):
        for role, name in health["missing"].items():
            print(f"  MISSING     {role}: {name}   (ollama pull {name})")
    else:
        print("  models      all required models present")

    # Does the vision model actually receive the pictures? Ollama accepts a
    # request-level "images" field and silently ignores it, which makes a
    # blind model look like a working one. This check settles it.
    if health.get("reachable") and not health.get("missing"):
        from .visioncheck import run_vision_check

        print("  checking that the vision model can see images...")
        check = run_vision_check(backend, config.vision_model)
        if check["ok"]:
            print(f"  vision      ok — {check['answer'].strip()[:70]}")
        else:
            print(f"  vision      FAILED — {check['reason']}")

    if not health.get("reachable"):
        print()
        print("  Ollama is not running. Start it with:  ollama serve")
        print("  or install it with:                     winget install Ollama.Ollama")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """End-to-end demo on a generated sample — no real photos required."""
    from .demo import build_demo_inbox

    agent = _agent(args)
    target = Path(args.watch_dir) if args.watch_dir else agent.config.watch_dir
    created = build_demo_inbox(target)
    agent.config.watch_dir = target
    print(f"Created {len(created)} sample file(s) in {target}")
    for path in created:
        print(f"  {path.name}")
    print()
    report = agent.run_once(force=True)
    print(report.headline())
    if report.digest:
        print()
        print(report.digest.to_markdown())
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="siesta",
        description="A local-first agent that naps until something changes.",
    )
    parser.add_argument("--version", action="version", version=f"siesta {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("--config", help="path to a config file")
    parser.add_argument("--watch-dir", help="folder to watch")
    parser.add_argument("--ollama-url", help="Ollama base URL")
    parser.add_argument("--vision-model", help="open-weight vision model")
    parser.add_argument("--text-model", help="open-weight text model")
    parser.add_argument("--embed-model", help="open-weight embedding model")
    parser.add_argument("--gate-model", default=None, help="optional cheap vision model used as a router")
    parser.add_argument(
        "--backend", choices=["auto", "ollama", "stub"], default="auto", help="inference backend"
    )
    parser.add_argument("--apply-tidy", action="store_true", help="actually move files (default: dry run)")
    parser.add_argument("--idle-seconds", type=int, default=None, help="only wake after this much idle time")
    parser.add_argument(
        "--energy-aware",
        action="store_true",
        help="stay quiet while on battery (conserve power)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create folders and config")
    p_init.set_defaults(func=cmd_init)

    p_scan = sub.add_parser("scan", help="run one pass now")
    p_scan.add_argument("--force", action="store_true", help="ignore the nap policy")
    p_scan.set_defaults(func=cmd_scan)

    p_status = sub.add_parser("status", help="show what the agent has been doing")
    p_status.set_defaults(func=cmd_status)

    p_watch = sub.add_parser("watch", help="run the overnight loop")
    p_watch.add_argument("--interval", type=int, help="minutes between passes")
    p_watch.set_defaults(func=cmd_watch)

    p_serve = sub.add_parser("serve", help="start the local web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_bench = sub.add_parser("bench", help="measure what the cascade saves")
    p_bench.add_argument("--out", help="where to write the JSON summary")
    p_bench.set_defaults(func=cmd_bench)

    p_doctor = sub.add_parser("doctor", help="check models, backend and folders")
    p_doctor.set_defaults(func=cmd_doctor)

    p_demo = sub.add_parser("demo", help="run the pipeline on a generated sample")
    p_demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
