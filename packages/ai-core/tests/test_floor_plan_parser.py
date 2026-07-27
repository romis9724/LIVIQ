"""floor_plan_parser 단위 — 대표 질의 12개+ (query.js 이식 사전 검증, LLM 미호출 0ms 경로).

파서 성공 경로는 이 테스트만으로 커버되고 llm mock을 아예 만들지 않는다(CRITICAL —
파서 성공 시 LLM 호출 0건은 tools/floor_plan 통합 테스트에서 별도 재확인).
"""

from __future__ import annotations

from ai_core.tools.floor_plan_parser import ParsedSpec, parse_query


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
