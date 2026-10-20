"""Chores — the individual jobs Siesta knows how to do.

Each chore is a small, self-contained unit:

    detect()  cheap, deterministic signal from filename / path / extension
    run()     the actual work, using the open-weight models it needs

Keeping them separate is what makes the cascade possible: the agent can run
``receipt`` on a folder of 40 receipts without ever invoking the reasoning
model, and can fall back to the reasoning model for the one file it did not
understand.
"""

from .base import ChoreContext, ChoreResult, BaseChore
from .chat import ChatChore
from .pantry import PantryChore
from .receipt import ReceiptChore
from .tidy import TidyChore

REGISTRY = {
    "pantry": PantryChore,
    "receipt": ReceiptChore,
    "chat": ChatChore,
    "tidy": TidyChore,
}


def get_chore(kind: str) -> BaseChore:
    cls = REGISTRY.get(kind)
    if cls is None:
        raise KeyError(f"unknown chore: {kind}")
    return cls()


__all__ = [
    "REGISTRY",
    "get_chore",
    "BaseChore",
    "ChoreContext",
    "ChoreResult",
    "PantryChore",
    "ReceiptChore",
    "ChatChore",
    "TidyChore",
]
