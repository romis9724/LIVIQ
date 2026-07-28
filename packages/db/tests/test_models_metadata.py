"""모델 메타데이터 sanity — DB 연결 없이 스키마 규약을 검증(docs/03 §3·5).

멀티테넌시·soft delete 규약이 코드에서 지켜지는지 빠르게 잡는 가드.
통합(RLS·실 DDL) 테스트는 testcontainers(H0-6)에서 별도로 다룬다.
"""

from __future__ import annotations

import pytest

from liviq_db.models import (
    NULLABLE_TENANT_TABLES,
    SOFT_DELETE_TABLES,
    TENANTLESS_TABLES,
    metadata,
)

BUSINESS_TABLES = sorted(set(metadata.tables) - TENANTLESS_TABLES)


@pytest.mark.parametrize("table_name", BUSINESS_TABLES)
def test_business_table_has_tenant_id(table_name: str) -> None:
    columns = metadata.tables[table_name].columns
    assert "tenant_id" in columns, f"{table_name}에 tenant_id 누락(멀티테넌시 §1)"


@pytest.mark.parametrize("table_name", BUSINESS_TABLES)
def test_tenant_id_not_null_except_exceptions(table_name: str) -> None:
    tenant_col = metadata.tables[table_name].columns["tenant_id"]
    if table_name in NULLABLE_TENANT_TABLES:
        assert tenant_col.nullable, f"{table_name}.tenant_id는 NULL 허용 대상(§5)"
    else:
        assert not tenant_col.nullable, f"{table_name}.tenant_id는 NOT NULL이어야 함(§5)"


@pytest.mark.parametrize("table_name", sorted(SOFT_DELETE_TABLES))
def test_soft_delete_tables_have_deleted_at(table_name: str) -> None:
    columns = metadata.tables[table_name].columns
    assert "deleted_at" in columns, f"{table_name}은 soft delete 대상 — deleted_at 필요(§3)"


def test_no_unexpected_deleted_at() -> None:
    """soft delete 대상 외 테이블에 deleted_at이 새지 않는지(§3)."""
    for table_name, table in metadata.tables.items():
        if table_name in SOFT_DELETE_TABLES:
            continue
        assert "deleted_at" not in table.columns, f"{table_name}에 예상 밖 deleted_at"


def test_tenant_scope_table_count() -> None:
    """도메인 30종 + tenant_keys(H2-1) + inquiry_events(H2-3) + auth_tokens(H7-1)
    + document_versions(H8-2) 등록 확인.

    H8-1(ADR-0015): notice_drafts 제거·notice_attachments 신설 — 순증감 0(합계 불변).
    H8-4(ADR-0017): code_groups·codes 신설 — +2.
    H8-9(ADR-0018): inquiry_categories 폐기(코드 그룹 흡수) — -1.
    H9-1(ADR-0019): household_geometries 신설(세대 3D 폴리곤) — +1.
    H9-5: parking_layouts·parking_vehicles 신설(지하주차장 배치도·차량) — +2.
    H15-1: ai_backend_config 신설(전역 LLM 백엔드 설정 단일 행) — +1.
    H15-3: ai_backend_config 컬럼 확장만(테이블 순증감 0).
    """
    assert len(metadata.tables) == 39


def test_ai_backend_config_optional_columns_are_nullable() -> None:
    """H15-3 확장 컬럼은 전부 NULL 허용 — NULL이 곧 env/코드 기본값 폴백 계약이다(§4.7).

    NOT NULL로 바뀌면 "설정 안 함"을 표현할 수 없어 폴백이 무너진다.
    """
    columns = metadata.tables["ai_backend_config"].columns
    for name in (
        "api_key",
        "reasoning_effort",
        "embedding_base_url",
        "embedding_model",
        "embedding_api_key",
        "chunk_max_tokens",
        "retrieval_top_k",
        "llm_max_output_tokens",
        "llm_timeout_s",
        "tool_confidence",
        "answer_cache_ttl_s",
    ):
        assert name in columns, f"ai_backend_config.{name} 누락(H15-3 §4.7)"
        assert columns[name].nullable, f"ai_backend_config.{name}은 NULL 허용이어야 함(폴백 계약)"
