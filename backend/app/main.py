from __future__ import annotations

import logging
from datetime import datetime, UTC
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.explore import router as explore_router
from backend.app.api.routes.query import router as query_router
from backend.app.bootstrap import get_services


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cricatlas.api")


def create_app() -> FastAPI:
    app = FastAPI(title="CricAtlas API", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_trace(request: Request, call_next):
        trace_id = str(uuid4())
        started = perf_counter()
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        logger.info("%s | %s | start %s %s", started_at, trace_id, request.method, request.url.path)
        response = await call_next(request)
        duration_ms = round((perf_counter() - started) * 1000, 2)
        finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        response.headers["x-trace-id"] = trace_id
        logger.info(
            "%s | %s | end %s %s status=%s duration_ms=%s",
            finished_at,
            trace_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/health")
    def health(services=Depends(get_services)):
        return {"status": "ok", **services["repository"].health()}

    app.include_router(query_router)
    app.include_router(explore_router)
    return app


app = create_app()
