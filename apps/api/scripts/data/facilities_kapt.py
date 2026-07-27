"""첫마을 4단지 시설물 실데이터 (H13-6 ② — K-apt A33982105 실측 + 표준 필수 설비 보강).

각 항목: name·type·location·memo(선택). type은 그래프 계통 렌즈 축(기존 데이터
"elevator" 관례에 맞춘 슬러그) — ALLOWED_TYPES로 오타를 방지한다.

facilities 테이블에 memo/description 컬럼이 없어(packages/db/src/liviq_db/models/
facilities.py 확인) memo는 DB에 별도 저장하지 않고 name에 " — " 구분자로 병기한다
(seed_facilities_kapt.py의 _full_name 참고).

출처 표기: 각 절 상단에 K-apt 실측 / 표준 보강을 주석으로 남긴다.
"""

from __future__ import annotations

from typing import Any

ALLOWED_TYPES: frozenset[str] = frozenset(
    {
        "elevator",
        "fire",
        "electric",
        "water",
        "heating",
        "parking",
        "security",
        "network",
        "community",
        "sanitation",
    }
)

_ELEVATOR_MEMO = "승강기관리 위탁·R형 수신반 연동·비상통화장치 포함"

# --- K-apt 실측: 승강기 11대(각 동 2대=10 + 커뮤니티동 1) ---
_ELEVATORS: tuple[dict[str, Any], ...] = tuple(
    {
        "name": f"{dong}동 {unit}호기 승강기",
        "type": "elevator",
        "location": f"{dong}동",
        "memo": _ELEVATOR_MEMO,
    }
    for dong in (401, 402, 403, 404, 405)
    for unit in (1, 2)
) + (
    {
        "name": "커뮤니티동 승강기",
        "type": "elevator",
        "location": "커뮤니티동",
        "memo": _ELEVATOR_MEMO,
    },
)

# --- K-apt 실측: 소방 ---
_FIRE_KAPT: tuple[dict[str, Any], ...] = (
    {"name": "화재수신반(R형)", "type": "fire", "location": "관리사무소"},
    {"name": "옥상문 자동개폐장치", "type": "fire", "location": "단지 공용"},
)

# --- 표준 보강: 소방(법정·통상 필수 설비) ---
_FIRE_STANDARD: tuple[dict[str, Any], ...] = (
    {"name": "소방펌프", "type": "fire", "location": "기계실"},
    {"name": "스프링클러 시스템", "type": "fire", "location": "단지 공용"},
    {"name": "옥내소화전", "type": "fire", "location": "단지 공용"},
    {"name": "비상발전기", "type": "fire", "location": "전기실"},
)

# --- K-apt 실측: 전기 ---
_ELECTRIC: tuple[dict[str, Any], ...] = (
    {"name": "수전설비(2250kW·단일계약)", "type": "electric", "location": "전기실"},
    {
        "name": "EV 완속충전기 8기(스탠드형·서울씨엔지)",
        "type": "electric",
        "location": "지상 주차장",
    },
)

# --- K-apt 실측: 급배수 ---
_WATER_KAPT: tuple[dict[str, Any], ...] = (
    {"name": "부스타 급수펌프", "type": "water", "location": "기계실"},
    {"name": "저수조", "type": "water", "location": "기계실"},
)

# --- 표준 보강: 급배수 ---
_WATER_STANDARD: tuple[dict[str, Any], ...] = (
    {"name": "배수펌프", "type": "water", "location": "지하주차장"},
    {"name": "오수펌프", "type": "water", "location": "기계실"},
)

# --- K-apt 실측: 난방 ---
_HEATING: tuple[dict[str, Any], ...] = (
    {"name": "지역난방 열교환기", "type": "heating", "location": "기계실"},
)

# --- K-apt 실측: 주차(정문 주차관제, 396면=지상39·지하357) ---
_PARKING: tuple[dict[str, Any], ...] = (
    {
        "name": "주차관제시스템(정문·긴급차 번호판 자동인식)",
        "type": "parking",
        "location": "정문",
        "memo": "주차 396면(지상39·지하357)",
    },
)

# --- K-apt 실측: 보안 ---
_SECURITY: tuple[dict[str, Any], ...] = (
    {"name": "CCTV 통합시스템(78대)", "type": "security", "location": "관리사무소"},
    {"name": "공동현관 출입시스템", "type": "security", "location": "단지 공용"},
)

# --- K-apt 실측: 통신 ---
_NETWORK: tuple[dict[str, Any], ...] = (
    {"name": "홈네트워크 서버", "type": "network", "location": "관리사무소"},
)

# --- K-apt 실측: 커뮤니티(7건) ---
_COMMUNITY: tuple[dict[str, Any], ...] = (
    {"name": "관리사무소", "type": "community", "location": "단지 공용"},
    {"name": "노인정", "type": "community", "location": "단지 공용"},
    {"name": "문고", "type": "community", "location": "단지 공용"},
    {"name": "어린이놀이터", "type": "community", "location": "단지 공용"},
    {"name": "유치원", "type": "community", "location": "단지 공용"},
    {"name": "커뮤니티공간", "type": "community", "location": "커뮤니티동"},
    {"name": "자전거보관소", "type": "community", "location": "단지 공용"},
)

# --- 표준 보강: 기타(위생/환기) ---
_SANITATION_STANDARD: tuple[dict[str, Any], ...] = (
    {"name": "지하주차장 환기팬", "type": "sanitation", "location": "지하주차장"},
)

FACILITIES: tuple[dict[str, Any], ...] = (
    _ELEVATORS
    + _FIRE_KAPT
    + _FIRE_STANDARD
    + _ELECTRIC
    + _WATER_KAPT
    + _WATER_STANDARD
    + _HEATING
    + _PARKING
    + _SECURITY
    + _NETWORK
    + _COMMUNITY
    + _SANITATION_STANDARD
)
