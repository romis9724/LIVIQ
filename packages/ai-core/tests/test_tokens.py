from ai_core.llm.tokens import estimate_tokens


def test_empty_text_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_korean_counts_per_char() -> None:
    assert estimate_tokens("관리비") == 3


def test_latin_counts_per_four_chars_rounded_up() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_mixed_korean_and_latin() -> None:
    # 한글 2 + 라틴/공백 5자(" abcd") → 2 + ceil(5/4)=2 → 4
    assert estimate_tokens("주차 abcd") == 4
