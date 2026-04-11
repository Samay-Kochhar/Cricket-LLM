from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.explore import router as explore_router
from backend.app.api.routes.query import router as query_router
from backend.app.bootstrap import get_services


def create_app() -> FastAPI:
    app = FastAPI(title="CricAtlas API", version="0.3.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(services=Depends(get_services)):
        return {"status": "ok", **services["repository"].health()}

    app.include_router(query_router)
    app.include_router(explore_router)
    return app


app = create_app()
