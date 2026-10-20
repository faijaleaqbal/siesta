"""Behavioural tests for the agent loop.

These are the tests that matter: does the agent stay asleep when nothing
changed, does it avoid the expensive model when the cheap gate is sure, and
does it stay quiet when it has nothing new to say?
"""

from __future__ import annotations

import time

from siesta.agent import Siesta
from siesta.backends import StubBackend
from siesta.config import Config


def make_agent(config: Config, backend: StubBackend) -> Siesta:
    return Siesta(config=config, backend=backend)


def write(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestNap:
    def test_sleeps_when_inbox_is_empty(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        report = agent.run_once()
        assert report.slept is True
        assert "nothing to watch" in report.reason
        assert backend.calls == []

    def test_sleeps_when_nothing_changed(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "chats" / "weekend.txt", "hello there")
        first = agent.run_once()
        assert first.slept is False
        calls_after_first = len(backend.calls)

        second = agent.run_once()
        assert second.slept is True
        assert "nothing changed" in second.reason
        # The second pass must not have called a model at all.
        assert len(backend.calls) == calls_after_first

    def test_touching_a_file_does_not_wake_the_agent(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        target = write(config.watch_dir / "chats" / "weekend.txt", "hello there")
        agent.run_once()
        calls_after_first = len(backend.calls)

        # Same bytes, new mtime — the classic "I reorganised my downloads" case.
        time.sleep(0.01)
        target.write_text("hello there", encoding="utf-8")

        report = agent.run_once()
        assert report.slept is True
        assert len(backend.calls) == calls_after_first

    def test_changed_content_does_wake_the_agent(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        target = write(config.watch_dir / "chats" / "weekend.txt", "first version")
        agent.run_once()
        calls_after_first = len(backend.calls)

        target.write_text("second version, quite different", encoding="utf-8")
        report = agent.run_once()
        assert report.slept is False
        assert len(backend.calls) > calls_after_first


class TestRouting:
    def test_metadata_route_avoids_the_model(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "receipts" / "receipt.png", "png-ish")
        report = agent.run_once()
        assert report.routes
        assert report.routes[0]["kind"] == "receipt"
        assert report.routes[0]["decided_by"] == "metadata"
        assert report.routed_by_metadata == 1

    def test_ambiguous_file_escalates(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "mystery.png", "png-ish")
        report = agent.run_once()
        assert report.routes
        # With no filename signal the agent must ask a model.
        assert report.routes[0]["decided_by"] in {"gate_model", "reason_model"}
        assert report.escalated == 1

    def test_chore_kind_is_respected(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "fridge" / "fridge.png", "png-ish")
        report = agent.run_once()
        assert report.routes[0]["kind"] == "pantry"
        assert report.results[0].kind == "pantry"


class TestDigest:
    def test_digest_is_written(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "chats" / "weekend.txt", "Ana: hi\nBen: hello")
        report = agent.run_once()
        assert report.digest_path
        from pathlib import Path

        content = Path(report.digest_path).read_text(encoding="utf-8")
        assert content.startswith("#")
        assert "tokens" in content

    def test_digest_is_recorded_in_the_store(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        write(config.watch_dir / "chats" / "weekend.txt", "Ana: hi")
        agent.run_once()
        assert agent.store.list_digests()
        assert agent.store.last_digest()["headline"]

    def test_second_identical_batch_is_treated_as_duplicate(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        target = config.watch_dir / "chats" / "weekend.txt"
        write(target, "Ana: hi\nBen: hello")
        agent.run_once()

        # Same meaning, different bytes — a duplicate should not produce a
        # second digest.
        target.write_text("Ana: hi\nBen: hello\nAna: see you", encoding="utf-8")
        report = agent.run_once()
        assert report.duplicate is True
        assert report.digest_path is None


class TestStatus:
    def test_status_reports_the_backend(self, config: Config, backend: StubBackend):
        agent = make_agent(config, backend)
        status = agent.status()
        assert status["backend"] == "stub"
        assert status["watch_dir"] == str(config.watch_dir)
