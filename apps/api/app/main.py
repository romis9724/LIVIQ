"""LIVIQ api — FastAPI 앱 팩토리(docs/09 §8.1, 02 §4).

H1: documents(업로드·인제스트 트리거)·assistant(SSE 질의) 라우터.
H2-1: auth(OAuth·세션)·onboarding(제출·명부 대조)·approvals(승인)·roster(명부 업로드).
H2-3: inquiries(접수·조회·배정·상태 + 키워드 분류·타임라인·알림).
H2-4: notices(발행 공지 조회 + AI 초안 생성·검수 발행·알림).
H2-5: fees(관리비 엑셀 업로드·검증·확정 적재 + 조회 + AI 설명 SSE).
H2-6: review_queue(AI 검수 큐 — 사후 검수 목록·승인/반려).
H3-1: facilities(시설 CRUD·장애/정비 이력 + outbox 원자 기록).
H4-3: dashboard(운영 통계 집계 — 질의·토큰·폴백·검수·캐시·민원·시설, MANAGER 전용).
H5-3: notifications(인앱 알림함 조회·읽음 처리 + 검수 반려 시 정정 알림 생성).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.routers import (
    approvals,
    assistant,
    auth,
    dashboard,
    documents,
    facilities,
    fees,
    inquiries,
    notices,
    notifications,
    onboarding,
    review_queue,
    roster,
)

# local 개발 웹 오리진(web-resident 3000·web-admin 3001). 운영 CORS는 배포 설정에서.
LOCAL_WEB_ORIGINS = ["http://localhost:3000", "http://localhost:3001"]


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    settings = get_settings()  # 부팅 시 env 검증 트리거(fail-closed)
    app = FastAPI(title="LIVIQ API", version="0.1.0")

    if settings.api_env == "local":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=LOCAL_WEB_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(approvals.router)
    app.include_router(roster.router)
    app.include_router(documents.router)
    app.include_router(assistant.router)
    app.include_router(assistant.facility_router)
    app.include_router(inquiries.router)
    app.include_router(inquiries.admin_router)
    app.include_router(notices.router)
    app.include_router(notices.admin_router)
    app.include_router(notifications.router)
    app.include_router(fees.router)
    app.include_router(fees.admin_router)
    app.include_router(review_queue.router)
    app.include_router(facilities.router)
    app.include_router(dashboard.router)
    return app


app = create_app()
