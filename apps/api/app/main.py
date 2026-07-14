"""LIVIQ api — FastAPI 앱 팩토리(docs/09 §8.1, 02 §4).

H1: documents(업로드·인제스트 트리거)·assistant(SSE 질의) 라우터.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.routers import assistant, documents


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    get_settings()  # 부팅 시 env 검증 트리거(fail-closed)
    app = FastAPI(title="LIVIQ API", version="0.1.0")

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(documents.router)
    app.include_router(assistant.router)
    return app


app = create_app()
