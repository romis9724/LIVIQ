"""PII 마스킹 테스트 — 패턴별 양성·음성(오탐 억제), 결정성, fail-closed 게이트(CRITICAL)."""

from __future__ import annotations

import pytest

from ai_core.masking import MaskingFailedError, MaskResult, ensure_masked, mask, unmask

# ── 패턴 양성 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("연락처는 010-1234-5678 입니다", "PHONE"),
        ("전화 01012345678 로 주세요", "PHONE"),
        ("사무실 02-345-6789", "PHONE"),
        ("메일 kim.dh+apt@example.co.kr 확인", "EMAIL"),
        ("주민번호 901231-1234567", "RRN"),
        ("생년월일: 1990-12-31", "BIRTH"),
        ("생일 1990.1.3", "BIRTH"),
        ("생년월일: 19901231", "BIRTH"),
        ("101동 302호 거주자", "UNIT"),
        ("동호수: 101-302", "UNIT"),
        ("계좌번호: 110-1234-567890", "ACCOUNT"),
    ],
)
def test_patterns_are_masked(text: str, kind: str) -> None:
    result = mask(text)
    assert kind in result.found_kinds
    assert f"<PII:{kind}:" in result.masked_text


# ── 패턴 음성 (오탐 억제) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "관리비는 253,000원입니다",  # 일반 금액
        "2026-07-14 공지",  # 날짜(생년월일 패턴은 매칭되나 이건 연도 문맥상 동일 — 아래 별도 확인)
        "총 302세대가 참여했습니다",  # 단순 숫자
        "회의는 3동에서 합니다",  # 호수 없는 동 단독
        "주문번호 12345678",  # 문맥 없는 8자리
    ],
)
def test_non_pii_not_over_masked(text: str) -> None:
    result = mask(text)
    # 날짜 패턴(YYYY-MM-DD)은 생년월일과 구분 불가 → 보수적으로 마스킹(과대 허용)
    if text == "2026-07-14 공지":
        assert result.found_kinds == frozenset({"BIRTH"})
    else:
        assert result.found_kinds == frozenset()
        assert result.masked_text == text


# ── 결정성·복원 ───────────────────────────────────────────────────────


def test_same_original_gets_same_placeholder() -> None:
    result = mask("010-1234-5678 그리고 다시 010-1234-5678")
    assert result.masked_text.count("<PII:PHONE:1>") == 2
    assert len(result.replacements) == 1


def test_different_originals_get_numbered_placeholders() -> None:
    result = mask("A: 010-1111-2222 / B: 010-3333-4444")
    assert "<PII:PHONE:1>" in result.masked_text
    assert "<PII:PHONE:2>" in result.masked_text


def test_unmask_roundtrip() -> None:
    original = "홍길동 연락처 010-1234-5678, 메일 hong@example.com"
    result = mask(original, extra_names=["홍길동"])
    assert unmask(result.masked_text, result.replacements) == original


def test_extra_names_masked_longest_first() -> None:
    result = mask("김철수와 김철수님", extra_names=["김철수"])
    assert "김철수" not in result.masked_text
    assert "NAME" in result.found_kinds


# ── 게이트 (fail-closed, CRITICAL) ────────────────────────────────────


def test_gate_passes_clean_masking() -> None:
    result = ensure_masked("연락처 010-1234-5678", extra_names=["박영희"])
    assert "010-1234-5678" not in result.masked_text


def test_gate_raises_on_residual_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    # 패턴 회귀·순서 버그로 잔존 PII가 남는 상황을 시뮬레이션
    monkeypatch.setattr("ai_core.masking.masker.detect_pii", lambda text: frozenset({"PHONE"}))
    with pytest.raises(MaskingFailedError, match="잔존"):
        ensure_masked("아무 텍스트")


def test_gate_raises_when_name_survives(monkeypatch: pytest.MonkeyPatch) -> None:
    # 이름 치환이 어떤 이유로든 누락된 상황 시뮬레이션
    monkeypatch.setattr(
        "ai_core.masking.masker.mask",
        lambda text, extra_names=(): MaskResult(
            masked_text=text, replacements={}, found_kinds=frozenset()
        ),
    )
    with pytest.raises(MaskingFailedError, match="이름"):
        ensure_masked("홍길동입니다", extra_names=["홍길동"])
