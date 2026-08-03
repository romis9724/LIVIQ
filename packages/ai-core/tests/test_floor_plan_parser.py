"""floor_plan_parser 단위 — 대표 질의 12개+ (query.js 이식 사전 검증, LLM 미호출 0ms 경로).

파서 성공 경로는 이 테스트만으로 커버되고 llm mock을 아예 만들지 않는다(CRITICAL —
파서 성공 시 LLM 호출 0건은 tools/floor_plan 통합 테스트에서 별도 재확인).
"""

from __future__ import annotations

from ai_core.tools.floor_plan_parser import ParsedSpec, parse_query, parse_unit


def test_room_and_element() -> None:
    assert parse_query("거실 콘센트 어디야") == ParsedSpec(elements=("콘센트",), rooms=("거실",))


def test_two_rooms_share_one_element() -> None:
    spec = parse_query("작은방이랑 큰방 콘센트 어디 있어")
    assert spec.elements == ("콘센트",)
    assert set(spec.rooms) == {"침실1", "안방"}


def test_safety_element_group_expands() -> None:
    spec = parse_query("안전시설 어디 있어")
    assert set(spec.elements) == {"소화기", "화재감지기", "경량칸막이"}
    assert spec.rooms == ()


def test_junction_box_synonym_두꺼비집() -> None:
    assert parse_query("두꺼비집 어디야") == ParsedSpec(elements=("분전함",))


def test_router_synonym_공유기() -> None:
    assert parse_query("공유기 어디 있어") == ParsedSpec(elements=("통신단자함",))


def test_lan_cable_synonym_랜선() -> None:
    assert parse_query("랜선 어디로 연결해") == ParsedSpec(elements=("TV·인터넷 단자",))


def test_water_valve_synonym_물_새() -> None:
    assert parse_query("물 새 어디서 잠그나요") == ParsedSpec(elements=("수도 차단밸브",))


def test_evacuation_hatch_synonym_비상구() -> None:
    assert parse_query("비상구가 어디야") == ParsedSpec(elements=("경량칸막이",))


def test_unknown_expression_returns_empty_spec() -> None:
    spec = parse_query("전기 나갔을 때 어디 봐야해")
    assert spec.is_empty


def test_generic_room_word_expands_to_bedroom_group() -> None:
    spec = parse_query("방 콘센트 어디")
    assert spec.elements == ("콘센트",)
    assert set(spec.rooms) == {"안방", "침실1", "침실2"}


def test_specific_room_synonym_skips_group_expansion() -> None:
    # "큰방"은 room_hits에 이미 "방"을 포함하므로 방 묶음이 중복 확장되지 않는다.
    spec = parse_query("큰방 콘센트 어디야")
    assert spec.rooms == ("안방",)


def test_generic_balcony_word_expands_to_all_balconies() -> None:
    spec = parse_query("발코니 어디야")
    assert spec.rooms == ("발코니(전면)", "발코니(후면)", "발코니(측면)")


def test_specific_balcony_skips_group_expansion() -> None:
    spec = parse_query("앞 발코니 콘센트 어디야")
    assert spec.elements == ("콘센트",)
    assert spec.rooms == ("발코니(전면)",)


def test_room_only_query_has_no_elements() -> None:
    assert parse_query("주방이 어디야") == ParsedSpec(rooms=("주방",))


# ── parse_unit(관리자 세대 지정, H20-17) ────────────────────────────────
#
# 마스킹(masking/masker.py의 UNIT 패턴)과 **같은 형태**를 인정해야 한다 — 갈리면 관리자
# 분기가 "동·호수 있음"으로 판정하고도 조회 대상이 없는 상태가 된다.


def test_parse_unit_reads_dong_and_ho() -> None:
    assert parse_unit("402동 201호 두꺼비집 어디?") == ("402", 201)


def test_parse_unit_allows_spacing_variants() -> None:
    assert parse_unit("404동301호 콘센트 위치") == ("404", 301)


def test_parse_unit_reads_dash_form_with_context_word() -> None:
    assert parse_unit("동호수 101-302 분전함 어디") == ("101", 302)


def test_parse_unit_ignores_facility_unit_number() -> None:
    """ "403동 2호기"는 세대가 아니라 설비 호기다(마스킹 패턴과 같은 예외)."""
    assert parse_unit("403동 2호기 승강기 점검일") is None


def test_parse_unit_returns_none_without_unit() -> None:
    assert parse_unit("콘센트 어디 있어?") is None
