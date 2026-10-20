"""Inference backends.

Siesta talks to *open-weight* models running on your own machine. The default
backend is Ollama (MIT), which serves models like Qwen2.5-VL, Qwen2.5 and
nomic-embed-text. A deterministic stub backend is included so the test suite
and a judge's laptop without models still work end to end.
"""

from .base import Backend, ChatResponse, Embedding
from .ollama import OllamaBackend
from .stub import StubBackend

__all__ = [
    "Backend",
    "ChatResponse",
    "Embedding",
    "OllamaBackend",
    "StubBackend",
    "build_backend",
]


def build_backend(config, kind: str = "auto") -> Backend:
    """Return a backend.

    kind="auto" prefers a live Ollama server and silently falls back to the
    deterministic stub when the server is unreachable, so the CLI never dies
    just because Ollama is not running yet.
    """
    kind = (kind or "auto").lower()
    if kind == "stub":
        return StubBackend()
    if kind == "ollama":
        return OllamaBackend(config)
    ollama = OllamaBackend(config)
    if ollama.available():
        return ollama
    return StubBackend(reason=f"Ollama not reachable at {config.ollama_url}")
