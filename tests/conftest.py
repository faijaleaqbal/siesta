"""Shared test fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siesta.backends import StubBackend  # noqa: E402
from siesta.config import Config  # noqa: E402
from siesta.store import Store  # noqa: E402


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    cfg = Config(
        home=tmp_path / "home",
        watch_dir=tmp_path / "inbox",
        data_dir=tmp_path / "data",
        digest_dir=tmp_path / "digests",
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
def store(config: Config) -> Store:
    s = Store(config.db_path)
    yield s
    s.close()


@pytest.fixture()
def backend() -> StubBackend:
    return StubBackend()
