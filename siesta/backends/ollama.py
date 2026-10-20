"""Ollama backend — open-weight models, served locally.

Ollama (MIT) is a local inference runtime. Siesta talks to it over plain HTTP
using the standard library, so there are no Python wheels to install and no
API key, no account, and no request ever leaves the machine.

Endpoints used:
    GET  /api/tags            — which models are installed
    POST /api/chat            — chat / vision completions (JSON-schema output)
    POST /api/embed           — embeddings
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Sequence

from .base import ChatResponse, Embedding

log = logging.getLogger("siesta.ollama")


class OllamaError(RuntimeError):
    pass


class OllamaBackend:
    """Client for a local Ollama server."""

    name = "ollama"

    def __init__(self, config) -> None:
        self.config = config
        self.base_url = config.ollama_url
        self.timeout = config.request_timeout
        # A local server under CPU load can drop a connection; a couple of
        # retries turn a crash into a slow answer.
        self.retries = 2
        self.retry_backoff = 2.0

    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            req = urllib.request.Request(
                self._url(path),
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code < 500 or attempt == self.retries:
                    raise OllamaError(f"HTTP {exc.code} from {path}: {detail}") from exc
                last_error = OllamaError(f"HTTP {exc.code} from {path}: {detail}")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                # The local server occasionally drops a connection under load —
                # on a CPU-only box it can be restarting a model between calls.
                last_error = exc
                if attempt == self.retries:
                    raise OllamaError(f"cannot reach Ollama at {self.base_url}: {exc}") from exc
            log.warning("Ollama request to %s failed (attempt %d/%d): %s", path, attempt + 1, self.retries + 1, last_error)
            time.sleep(self.retry_backoff * (attempt + 1))

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"invalid JSON from {path}: {body[:300]}") from exc

    def _get(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(self._url(path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=min(self.timeout, 15)) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------ #
    def available(self) -> bool:
        return bool(self._get("/api/tags"))

    def installed_models(self) -> list[str]:
        data = self._get("/api/tags")
        models = data.get("models", []) if isinstance(data, dict) else []
        return sorted({m.get("name", "") for m in models if isinstance(m, dict) and m.get("name")})

    def health(self) -> dict[str, Any]:
        installed = self.installed_models()
        required = {
            "vision": self.config.vision_model,
            "text": self.config.text_model,
            "embed": self.config.embed_model,
        }
        if self.config.gate_model:
            required["gate"] = self.config.gate_model
        missing = {role: name for role, name in required.items() if name not in installed}
        return {
            "backend": self.name,
            "url": self.base_url,
            "reachable": bool(installed) or self.available(),
            "installed": installed,
            "required": required,
            "missing": missing,
            "ready": bool(installed) and not missing,
        }

    # ------------------------------------------------------------------ #
    def chat(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        *,
        images: Sequence[str] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ) -> ChatResponse:
        messages = list(messages)
        if images:
            # Ollama expects the images **inside the message**, as raw base64
            # with no data-URL prefix. A request-level "images" field is
            # accepted but silently ignored, and the model then answers from
            # the text alone without ever seeing the picture - which is
            # indistinguishable from a working model unless you check.
            #
            # We send both placements so older and newer Ollama builds are
            # both covered.
            enriched: list[dict[str, Any]] = []
            for index, message in enumerate(messages):
                message = dict(message)
                if index == len(messages) - 1:
                    existing = list(message.get("images") or [])
                    message["images"] = existing + list(images)
                enriched.append(message)
            messages = enriched

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if num_predict is not None:
            payload["options"]["num_predict"] = num_predict
        if num_ctx is not None:
            payload["options"]["num_ctx"] = num_ctx
        if json_schema is not None:
            # Ollama structured outputs: pass a JSON Schema and the model is
            # constrained to emit valid JSON that matches it.
            payload["format"] = json_schema
        if images:
            payload["images"] = list(images)

        started = time.perf_counter()
        data = self._post("/api/chat", payload)
        latency_ms = int((time.perf_counter() - started) * 1000)

        message = data.get("message", {}) if isinstance(data, dict) else {}
        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        return ChatResponse(
            text=(message.get("content") or "").strip(),
            model=data.get("model", model) if isinstance(data, dict) else model,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            eval_tokens=int(data.get("eval_count", 0) or 0),
            # An image costs roughly a thousand prompt tokens. If that did not
            # happen, the picture did not reach the model.
            image_tokens=prompt_tokens if images else 0,
            raw=data if isinstance(data, dict) else {},
        )

    # ------------------------------------------------------------------ #
    def embed(self, model: str, inputs: Sequence[str]) -> list[Embedding]:
        inputs = list(inputs)
        if not inputs:
            return []
        data = self._post("/api/embed", {"model": model, "input": inputs})
        vectors = data.get("embeddings") or []
        out: list[Embedding] = []
        for vec in vectors:
            out.append(Embedding(vector=[float(x) for x in vec], model=data.get("model", model)))
        return out
