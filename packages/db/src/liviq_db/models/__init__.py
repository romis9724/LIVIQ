"""LIVIQ ORM 모델 — 도메인별 모듈을 모아 Base.metadata에 등록(docs/03).

Alembic env.py·testcontainers가 `Base.metadata`(= `metadata`)를 target으로 사용한다.
"""

from __future__ import annotations

from .base import Base
from .codes import Code, CodeGroup
from .conversations import AiFeedback, Citation, Conversation, Message
from .documents import ContentChunk, Document, DocumentVersion
from .facilities import Facility, Incident, MaintenanceLog
from .fees import ExcelUpload, Fee
from .inquiries import Inquiry, InquiryEvent
from .notices import Notice, NoticeAttachment, Notification
from .ops import AiEvalGolden, AuditLog, Job, OutboxEvent
from .plans import FloorPlan, PlanDevice
from .tenants import Building, Household, Tenant, UnitType
from .users import AuthToken, Consent, PiiVault, TenantKey, User, UserRole

metadata = Base.metadata

# soft delete(deleted_at) 적용 테이블(docs/03 §3)
SOFT_DELETE_TABLES = frozenset({"documents", "notices", "inquiries", "facilities", "users"})

# tenant_id 격리 표준에서 제외되는 테이블(docs/03 §5)
#  - tenants: tenant_id 없음(단지 자체)
#  - ai_eval_golden: tenant_id NULL 허용(공용 골든셋)
TENANTLESS_TABLES = frozenset({"tenants"})
NULLABLE_TENANT_TABLES = frozenset({"ai_eval_golden"})

__all__ = [
    "AiEvalGolden",
    "AiFeedback",
    "AuditLog",
    "AuthToken",
    "Base",
    "Building",
    "Citation",
    "Code",
    "CodeGroup",
    "Consent",
    "ContentChunk",
    "Conversation",
    "Document",
    "DocumentVersion",
    "ExcelUpload",
    "Facility",
    "Fee",
    "FloorPlan",
    "Household",
    "Incident",
    "Inquiry",
    "InquiryEvent",
    "Job",
    "MaintenanceLog",
    "Message",
    "Notice",
    "NoticeAttachment",
    "Notification",
    "NULLABLE_TENANT_TABLES",
    "OutboxEvent",
    "PiiVault",
    "PlanDevice",
    "SOFT_DELETE_TABLES",
    "TENANTLESS_TABLES",
    "Tenant",
    "TenantKey",
    "UnitType",
    "User",
    "UserRole",
    "metadata",
]
