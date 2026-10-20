"""Tests for the individual chores."""

from __future__ import annotations

from pathlib import Path

from siesta.chores import ChoreContext, get_chore
from siesta.chores.base import ChoreResult
from siesta.config import Config
from siesta.store import Store


def make_ctx(backend, store: Store, config: Config) -> ChoreContext:
    return ChoreContext(backend=backend, store=store, config=config, receipt=None)


def write_png(path: Path) -> Path:
    from siesta.demo import write_png as _write

    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, 4, 4, [[(10, 20, 30)] * 4 for _ in range(4)])
    return path


class TestPantry:
    def test_extracts_items_and_builds_a_shopping_list(self, config: Config, backend, store: Store):
        ctx = make_ctx(backend, store, config)
        photo = write_png(config.watch_dir / "fridge" / "fridge.png")
        result = get_chore("pantry").run(photo, ctx)

        assert result.ok is True
        assert result.data["items_seen"] > 0
        names = [i["name"] for i in store.list_items()]
        assert "milk" in names
        assert store.get_state("shopping_list") is not None

    def test_flags_items_that_need_using(self, config: Config, backend, store: Store):
        ctx = make_ctx(backend, store, config)
        photo = write_png(config.watch_dir / "fridge" / "fridge.png")
        result = get_chore("pantry").run(photo, ctx)
        # The stub fixture includes spinach with a 2 day expiry.
        assert any("spinach" in i["name"] for i in result.data["use_first"])

    def test_detect_uses_the_folder_name(self, config: Config):
        chore = get_chore("pantry")
        confidence, reason = chore.detect(Path("/tmp/fridge/photo.jpg"))
        assert confidence > 0.9


class TestReceipt:
    def test_records_an_expense(self, config: Config, backend, store: Store):
        ctx = make_ctx(backend, store, config)
        photo = write_png(config.watch_dir / "receipts" / "receipt.png")
        result = get_chore("receipt").run(photo, ctx)

        assert result.ok is True
        assert result.data["merchant"] == "Corner Store"
        assert store.expense_total() == 23.88
        assert len(store.list_expenses()) == 1
        # The printed total and the sum of the lines should agree.
        assert result.data["consistent"] is True


class TestChat:
    def test_summarises_a_transcript(self, config: Config, backend, store: Store):
        ctx = make_ctx(backend, store, config)
        transcript = config.watch_dir / "chats" / "weekend.txt"
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("Ana: are we still on?\nBen: yes 6pm", encoding="utf-8")

        result = get_chore("chat").run(transcript, ctx)
        assert result.ok is True
        assert result.data["summary"]
        assert "Saturday" in result.data["summary"]

    def test_needs_reasoning(self):
        assert get_chore("chat").needs_reasoning is True


class TestTidy:
    def test_dry_run_does_not_move_files(self, config: Config, backend, store: Store):
        ctx = make_ctx(backend, store, config)
        loose = config.watch_dir / "invoice-jan.pdf"
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_text("pdf-ish", encoding="utf-8")

        result = get_chore("tidy").run(loose, ctx)
        assert result.data["dry_run"] is True
        assert loose.exists()

    def test_apply_moves_files(self, config: Config, backend, store: Store):
        config.apply_tidy = True
        ctx = make_ctx(backend, store, config)
        loose = config.watch_dir / "invoice-jan.pdf"
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_text("pdf-ish", encoding="utf-8")

        result = get_chore("tidy").run(loose, ctx)
        assert result.data["applied"] is True
        assert (config.watch_dir / "invoices" / "invoice-jan.pdf").exists()

    def test_refuses_to_move_outside_the_watched_folder(self, config: Config, backend, store: Store):
        config.apply_tidy = True
        ctx = make_ctx(backend, store, config)
        loose = config.watch_dir / "invoice-jan.pdf"
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_text("pdf-ish", encoding="utf-8")

        # Force a malicious destination through the model interface.
        original = backend.chat

        def evil(model, messages, **kwargs):
            response = original(model, messages, **kwargs)
            if "TASK: TIDY" in str(messages):
                response.text = '{"moves": [{"from": "invoice-jan.pdf", "to": "../../escape.pdf", "reason": "x"}]}'
            return response

        backend.chat = evil  # type: ignore[assignment]
        result = get_chore("tidy").run(loose, ctx)
        assert loose.exists()
        assert result.data["moves"] == []
        assert result.data["skipped"]


class TestChoreRegistry:
    def test_all_chores_are_registered(self):
        for kind in ("pantry", "receipt", "chat", "tidy"):
            assert get_chore(kind).kind == kind

    def test_unknown_chore_raises(self):
        import pytest

        with pytest.raises(KeyError):
            get_chore("nope")
