"""LIVIQ api — FastAPI 앱 팩토리(docs/09 §8.1).

빈 앱. 라우터·미들웨어는 후속 H 단계에서 추가한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    get_settings()  # 부팅 시 env 검증 트리거(fail-closed)
    app = FastAPI(title="LIVIQ API", version="0.1.0")

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
