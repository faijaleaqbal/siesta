"""Siesta — a local-first agent that naps until something changes.

Core idea: the agent's default posture is *not acting*. It watches a local
folder, hashes what it sees, and only spends model tokens when something is
actually new. When it does wake up, it uses the cheapest open-weight model
that can do the job and escalates to a bigger one only when it is unsure.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
