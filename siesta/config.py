"""Configuration for Siesta.

Resolution order (last wins):
  1. Built-in defaults
  2. ~/.siesta/config.json
  3. Environment variables (SIESTA_*)

Everything is overridable on the command line too, so a judge can point
Siesta at a different model in one line — swapping models is a first-class
feature, not an accident.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .util import ensure_dir

ENV_PREFIX = "SIESTA_"


@dataclass
class Config:
    # --- Paths ------------------------------------------------------------ #
    home: Path = field(default_factory=lambda: Path.home() / ".siesta")
    watch_dir: Path = field(default_factory=lambda: Path.home() / "Siesta-Inbox")
    data_dir: Path = field(default_factory=lambda: Path.home() / ".siesta" / "data")
    digest_dir: Path = field(default_factory=lambda: Path.home() / ".siesta" / "digests")

    # --- Inference -------------------------------------------------------- #
    ollama_url: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen2.5vl:3b"
    text_model: str = "qwen2.5:3b-instruct"
    embed_model: str = "nomic-embed-text"
    # Optional cheap vision model used only as a router. Leave empty to use
    # the deterministic metadata router instead.
    gate_model: str = ""
    request_timeout: int = 300
    max_images: int = 4

    # --- The cascade ------------------------------------------------------ #
    # Confidence at or above this is trusted and routed without escalation.
    gate_threshold: float = 0.62
    # Confidence below this makes the agent ask the reasoning model instead.
    escalate_threshold: float = 0.55
    # Soft ceiling on reasoning-model tokens per chore.
    reason_budget: int = 700
    # Digest prose budget.
    digest_budget: int = 500

    # --- Nap policy ------------------------------------------------------- #
    nap_minutes: int = 15
    # Only wake up once the human has been idle this long (0 = never gate).
    idle_seconds: int = 0
    # Skip work entirely while on battery / metered connection.
    # Opt-in: local inference is free in money but not in watts, and on a
    # laptop that lives on battery this would otherwise never run.
    energy_aware: bool = False

    # --- Behaviour -------------------------------------------------------- #
    # Tidy chore is a dry run unless explicitly applied.
    apply_tidy: bool = False
    # Delete a source photo after it has been consumed.
    consume_sources: bool = False
    # Minimum tokens/day of history kept in the digest index.
    keep_digests: int = 60

    # ------------------------------------------------------------------ #
    def __post_init__(self) -> None:
        for name in ("home", "watch_dir", "data_dir", "digest_dir"):
            setattr(self, name, Path(getattr(self, name)).expanduser())
        self.ollama_url = self.ollama_url.rstrip("/")

    # ------------------------------------------------------------------ #
    @property
    def db_path(self) -> Path:
        return self.data_dir / "siesta.sqlite3"

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.watch_dir, self.data_dir, self.digest_dir):
            ensure_dir(path)

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        cfg = cls()
        cfg_path = Path(path) if path else cfg.config_path
        if cfg_path.exists():
            try:
                raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                raw = {}
            for key, value in (raw or {}).items():
                if key in {f.name for f in fields(cls)}:
                    current = getattr(cfg, key)
                    if isinstance(current, Path):
                        value = Path(str(value)).expanduser()
                    elif isinstance(current, bool):
                        value = str(value).lower() in {"1", "true", "yes", "on"}
                    elif isinstance(current, int) and not isinstance(current, bool):
                        value = int(value)
                    elif isinstance(current, float):
                        value = float(value)
                    setattr(cfg, key, value)

        cfg._apply_env()
        return cfg

    def _apply_env(self) -> None:
        for f in fields(self):
            env_key = ENV_PREFIX + f.name.upper()
            if env_key not in os.environ:
                continue
            raw = os.environ[env_key]
            current = getattr(self, f.name)
            try:
                if isinstance(current, bool):
                    value: Any = raw.lower() in {"1", "true", "yes", "on"}
                elif isinstance(current, Path):
                    value = Path(raw).expanduser()
                elif isinstance(current, int) and not isinstance(current, bool):
                    value = int(raw)
                elif isinstance(current, float):
                    value = float(raw)
                else:
                    value = raw
            except (TypeError, ValueError):
                continue
            setattr(self, f.name, value)

    # ------------------------------------------------------------------ #
    def save(self, path: Path | None = None) -> Path:
        target = Path(path) if path else self.config_path
        ensure_dir(target.parent)
        data = {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(self).items()}
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return target

    def redacted(self) -> dict[str, Any]:
        """Config safe to show in logs / the web UI."""
        data = asdict(self)
        for key, value in list(data.items()):
            if isinstance(value, Path):
                data[key] = str(value)
        return data
