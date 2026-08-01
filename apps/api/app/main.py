"""LIVIQ api — FastAPI 앱 팩토리(docs/09 §8.1, 02 §4).

H1: documents(업로드·인제스트 트리거)·assistant(SSE 질의) 라우터.
H2-1: auth(이메일+비밀번호·세션)·onboarding(제출·명부 대조)·approvals(승인)·roster(명부 업로드).
H2-3: inquiries(접수·조회·배정·상태 + 키워드 분류·타임라인·알림).
H8-1: notices(공지 게시판 — 작성·수정·삭제·고정·예약·첨부 + 발행 알림, ADR-0015).
H2-5: fees(관리비 엑셀 업로드·검증·확정 적재 + 조회 + AI 설명 SSE).
H3-1: facilities(시설 CRUD·장애/정비 이력 + outbox 원자 기록).
H4-3: dashboard(운영 통계 집계 — 질의·토큰·폴백·검수·캐시·민원·시설, MANAGER 전용).
H5-3: notifications(인앱 알림함 조회·읽음 처리 + 검수 반려 시 정정 알림 생성).
H7-2: admin_tenants(단지 생성·소장 초대, SYS_ADMIN)·staff(직원 초대·목록·비활성화, MANAGER).
H8-4: codes(공통 코드 레지스트리 CRUD — 쓰기 MANAGER, 조회 MANAGER·STAFF, ADR-0017).
H8-5: households(동/호수 관리 — 동·세대 CRUD + 층·호 범위 일괄 생성, MANAGER 전용).
H9-1: twin(단지 트윈 — units.json geometry 업로드·조회 + occupancy 오버레이, MANAGER, ADR-0019).
H9-5: parking(주차장 대시보드 — 지하주차장 배치도·입주민 차량 조회, MANAGER 전용).
H13-3: floor_plans(입주민 본인 세대 평면도 조회 — 동·호 선택 없음, RESIDENT 전용).
H15-1: ai_config(LLM 백엔드 런타임 설정 — 조회·저장·연결 테스트, SYS_ADMIN 전용).
H15-3: ai_reindex(임베딩·청킹 변경 반영 — 전 단지 재색인 트리거·진행 조회, SYS_ADMIN 전용).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import get_settings
from app.deps import verify_db_role
from app.routers import (
    admin_tenants,
    ai_config,
    ai_reindex,
    approvals,
    assistant,
    auth,
    codes,
    dashboard,
    documents,
    facilities,
    fees,
    floor_plans,
    households,
    inquiries,
    notices,
    notifications,
    onboarding,
    parking,
    roster,
    staff,
    twin,
)


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """기동 시 DB 접속 롤 검증 — RLS 이중 방어 2층의 성립 조건(H10-2, docs/03 §5.1).

    local은 경고만, 그 외 환경은 예외를 그대로 올려 기동을 중단시킨다(fail-closed).
    """
    await verify_db_role()
    yield


def create_app() -> FastAPI:
    settings = get_settings()  # 부팅 시 env 검증 트리거(fail-closed)
    app = FastAPI(title="LIVIQ API", version="0.1.0", lifespan=_lifespan)

    # 웹 앱은 별도 출처(3000·3001)라 세션 쿠키 전송에 credentials CORS 필수(ADR-0011).
    # allow_credentials=True는 와일드카드 오리진과 양립 불가 — WEB_ORIGINS로 명시.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    app.include_router(auth.router)
    app.include_router(onboarding.router)
    app.include_router(approvals.router)
    app.include_router(admin_tenants.router)
    app.include_router(ai_config.router)
    app.include_router(ai_reindex.router)
    app.include_router(staff.router)
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
    app.include_router(facilities.router)
    app.include_router(dashboard.router)
    app.include_router(codes.router)
    app.include_router(codes.code_router)
    app.include_router(households.router)
    app.include_router(households.household_router)
    app.include_router(twin.router)
    app.include_router(parking.router)
    app.include_router(parking.resident_router)
    app.include_router(floor_plans.router)
    return app


app = create_app()
