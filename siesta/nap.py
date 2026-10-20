"""The watch loop.

``siesta watch`` is the mode you leave running overnight. It wakes up on an
interval, asks the nap policy whether this is a good time, and does the work
only if there is something to do.

The loop is deliberately dull: sleep, check, act, sleep. Nothing spins, and
an idle Siesta costs zero tokens and roughly zero CPU.
"""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass
from typing import Any, Callable

from .agent import RunReport, Siesta

log = logging.getLogger("siesta.nap")


@dataclass
class NapStats:
    passes: int = 0
    asleep_passes: int = 0
    handled: int = 0
    tokens: int = 0


class Watcher:
    """Polls the watched folder and runs the agent when something changed."""

    def __init__(
        self,
        agent: Siesta,
        *,
        interval: int | None = None,
        on_report: Callable[[RunReport], None] | None = None,
    ) -> None:
        self.agent = agent
        self.interval = interval or agent.config.nap_minutes
        self.on_report = on_report
        self.stats = NapStats()
        self._stop = False

    # ------------------------------------------------------------------ #
    def stop(self, *_args: Any) -> None:
        log.info("stopping watcher")
        self._stop = True

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    # ------------------------------------------------------------------ #
    def tick(self) -> RunReport:
        report = self.agent.run_once()
        self.stats.passes += 1
        if report.slept:
            self.stats.asleep_passes += 1
        else:
            self.stats.handled += 1
            self.stats.tokens += report.tokens
        if self.on_report:
            self.on_report(report)
        return report

    def run_forever(self) -> NapStats:
        self.install_signal_handlers()
        log.info(
            "watching %s every %d minute(s) — Ctrl-C to stop",
            self.agent.config.watch_dir,
            self.interval,
        )
        while not self._stop:
            try:
                self.tick()
            except KeyboardInterrupt:
                break
            except Exception as exc:  # pragma: no cover - keep the loop alive
                log.exception("watcher iteration failed: %s", exc)
            # Sleep in short slices so Ctrl-C is responsive.
            slept = 0.0
            while slept < self.interval * 60 and not self._stop:
                time.sleep(min(1.0, self.interval * 60 - slept))
                slept += 1.0
        return self.stats
