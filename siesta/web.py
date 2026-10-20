"""A small local web UI.

Bound to 127.0.0.1 by default. The UI is a convenience, not the point — the
point is that it is served from the same machine as the models, so the photos
you drop in never travel anywhere.

Run it with:  siesta serve
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from .agent import Siesta
from .config import Config
from .util import ensure_dir, now_iso

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    config.ensure_dirs()

    app = FastAPI(title="Siesta", docs_url="/api/docs")
    agent = Siesta(config=config)

    # ------------------------------------------------------------------ #
    @app.get("/")
    def index() -> Any:
        index_file = WEB_DIR / "index.html"
        if not index_file.exists():
            return JSONResponse({"error": "web assets not found"}, status_code=500)
        return FileResponse(str(index_file))

    @app.get("/app.js")
    def app_js() -> Any:
        return FileResponse(str(WEB_DIR / "app.js"))

    @app.get("/style.css")
    def style_css() -> Any:
        return FileResponse(str(WEB_DIR / "style.css"))

    # ------------------------------------------------------------------ #
    @app.get("/api/status")
    def status() -> Any:
        data = agent.status()
        data["nap_policy"] = {
            "idle_seconds": config.idle_seconds,
            "energy_aware": config.energy_aware,
            "nap_minutes": config.nap_minutes,
        }
        return data

    @app.post("/api/scan")
    def scan(force: bool = True) -> Any:
        report = agent.run_once(force=force)
        return report.to_dict()

    @app.get("/api/digests")
    def digests(limit: int = 20) -> Any:
        return agent.store.list_digests(limit=limit)

    @app.get("/api/digests/latest")
    def latest_digest() -> Any:
        row = agent.store.last_digest()
        if not row:
            return {"digest": None}
        return {"digest": row}

    @app.get("/api/items")
    def items() -> Any:
        return {
            "items": agent.store.list_items(),
            "shopping_list": agent.store.get_state("shopping_list", []),
            "use_first": agent.store.get_state("use_first", []),
        }

    @app.get("/api/expenses")
    def expenses(limit: int = 50) -> Any:
        return {"expenses": agent.store.list_expenses(limit=limit)}

    @app.get("/api/ledger")
    def ledger() -> Any:
        return {
            "totals": agent.store.token_totals(),
            "by_phase": agent.store.events_by_phase(),
        }

    # ------------------------------------------------------------------ #
    @app.post("/api/upload")
    async def upload(request: Request) -> Any:
        """Drop a photo in from the browser — straight onto your disk.

        The body is the raw file bytes and the filename is a query parameter.
        Using a raw body instead of a multipart form keeps the web UI's
        dependency list down to FastAPI and uvicorn.
        """
        name = request.query_params.get("filename") or "upload.bin"
        payload = await request.body()
        if not payload:
            raise HTTPException(status_code=400, detail="empty upload")

        inbox = ensure_dir(Path(config.watch_dir))
        safe = Path(name).name
        stem = safe.rsplit(".", 1)[0][:60] or "upload"
        suffix = Path(safe).suffix or ".bin"
        target = inbox / f"{stem}{suffix}"
        counter = 1
        while target.exists():
            target = inbox / f"{stem}-{counter}{suffix}"
            counter += 1
        target.write_bytes(payload)
        return {"saved": str(target), "ts": now_iso()}

    @app.post("/api/tidy/apply")
    def tidy_apply() -> Any:
        config.apply_tidy = True
        try:
            report = agent.run_once(force=True)
        finally:
            config.apply_tidy = False
        return report.to_dict()

    @app.get("/api/bench")
    def bench() -> Any:
        from .bench import run_benchmark

        result = run_benchmark(agent)
        return result.summary()

    # ------------------------------------------------------------------ #
    @app.exception_handler(Exception)
    async def unhandled(_request, exc: Exception) -> Any:  # pragma: no cover
        return JSONResponse({"error": str(exc)}, status_code=500)

    return app


__all__ = ["create_app"]
