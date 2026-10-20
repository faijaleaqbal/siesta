"""Tests for the local store."""

from __future__ import annotations

import pytest

from siesta.store import Store


class TestItems:
    def test_upsert_creates_then_updates(self, store: Store):
        item_id = store.upsert_item(name="milk", quantity=1, unit="carton", category="dairy")
        assert item_id > 0
        assert len(store.list_items()) == 1

        same_id = store.upsert_item(name="Milk", quantity=2, unit="carton", category="dairy")
        assert same_id == item_id
        assert len(store.list_items()) == 1
        assert store.list_items()[0]["quantity"] == 2

    def test_match_by_name(self, store: Store):
        store.upsert_item(name="spinach", category="vegetable")
        assert store.match_item("Spinach", None) is not None

    def test_match_by_embedding(self, store: Store):
        vector = [0.1] * 8 + [0.9] * 8
        store.upsert_item(name="greek yoghurt", embedding=vector)
        match = store.match_item("yoghurt", vector)
        assert match is not None
        assert match["name"] == "greek yoghurt"

    def test_no_match_for_unrelated_embedding(self, store: Store):
        store.upsert_item(name="spinach", embedding=[1.0, 0.0])
        assert store.match_item("chainsaw", [0.0, 1.0]) is None

    def test_expiry_date_is_derived(self, store: Store):
        store.upsert_item(name="milk", expiry_days=3)
        item = store.list_items()[0]
        assert item["expiry_date"] is not None
        assert item["expiry_days"] == 3


class TestSeenFiles:
    def test_mark_and_lookup(self, store: Store):
        store.mark_seen("/a/b.png", fingerprint="1-2", sha256="abc", size=10, mtime=1.0)
        row = store.seen("/a/b.png")
        assert row is not None
        assert row["sha256"] == "abc"

    def test_touch_updates_fingerprint(self, store: Store):
        store.mark_seen("/a/b.png", fingerprint="1-2", sha256="abc", size=10, mtime=1.0)
        store.mark_seen("/a/b.png", fingerprint="1-3", sha256="abc", size=10, mtime=2.0)
        assert store.seen("/a/b.png")["fingerprint"] == "1-3"
        assert store.seen_count() == 1


class TestLedger:
    def test_totals_sum(self, store: Store):
        store.record_event(phase="vision", model="m", latency_ms=100, prompt_tokens=10, eval_tokens=5)
        store.record_event(phase="reason", model="m", latency_ms=200, prompt_tokens=20, eval_tokens=7)
        totals = store.token_totals()
        assert totals["calls"] == 2
        assert totals["prompt_tokens"] == 30
        assert totals["eval_tokens"] == 12
        assert totals["total_tokens"] == 42
        assert totals["latency_ms"] == 300

    def test_events_by_phase(self, store: Store):
        store.record_event(phase="vision", model="vlm")
        store.record_event(phase="vision", model="vlm")
        store.record_event(phase="digest", model="llm")
        phases = {row["phase"]: row for row in store.events_by_phase()}
        assert phases["vision"]["calls"] == 2
        assert phases["digest"]["calls"] == 1


class TestState:
    def test_roundtrip(self, store: Store):
        store.set_state("shopping_list", [{"name": "milk"}])
        assert store.get_state("shopping_list") == [{"name": "milk"}]

    def test_missing_key(self, store: Store):
        assert store.get_state("nope", default=[]) == []


class TestThreadSafety:
    def test_the_store_can_be_used_from_another_thread(self, store: Store):
        """The web UI runs its handlers in a threadpool.

        A SQLite connection bound to the thread that opened it raises
        "SQLite objects created in a thread can only be used in that same
        thread" the moment a request handler touches it.
        """
        import threading

        errors: list[Exception] = []

        def worker() -> None:
            try:
                store.upsert_item(name="milk", quantity=2)
                store.record_event(phase="vision", model="m", prompt_tokens=10)
                store.set_state("k", {"v": 1})
                assert store.list_items()
                assert store.token_totals()["calls"] >= 1
            except Exception as exc:  # pragma: no cover - the failure we guard
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors, errors


class TestExpenses:
    def test_add_and_total(self, store: Store):
        store.add_expense(merchant="Corner Store", total=12.5, currency="USD", lines=[{"name": "milk"}], source="x.png")
        store.add_expense(merchant="Cafe", total=4.0, currency="USD", lines=[], source="y.png")
        assert store.expense_total() == pytest.approx(16.5)
        assert len(store.list_expenses()) == 2

    def test_lines_are_parsed(self, store: Store):
        store.add_expense(merchant="Cafe", total=4.0, currency="USD", lines=[{"name": "tea"}], source="y.png")
        assert store.list_expenses()[0]["lines"][0]["name"] == "tea"
