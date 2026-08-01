"""히스토리 관련성 선별 — 후보 턴 중 질문과 관련된 것만 고른다(ADR-0027 결정 2).

대화가 서버에 영구화되면서(H19-8) 후보 풀이 길어졌다. 무관한 턴을 그대로 실으면 도구
결정 turn이 오염된다(주차 얘기 끝에 관리비를 물었는데 주차 도구를 부르는 식) — 그래서
후보는 넓게(10턴) 받고 주입은 좁게(3턴) 한다.

1차 구현은 **lexical**이다: LLM·임베딩·DB 호출 없는 순수 함수라 지연 0이고 결정적이다.
임베딩 승격은 실측이 이 한계를 보일 때만(ADR-0027 — 측정 없이 비용을 들이지 않는다).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# 후보 풀(턴) — api가 DB에서 읽어올 메시지 상한(× 2)의 근거.
HISTORY_CANDIDATE_TURNS = 10
# 실제 주입 상한(턴) — 넓힌 것은 후보뿐, 프롬프트에 실리는 양은 그대로다(토큰=비용).
HISTORY_INJECT_TURNS = 3
# bigram 집합을 만들 수 없는 길이(한 글자 이하)는 점수 0으로 둔다.
_MIN_BIGRAM_LEN = 2


def select_relevant_messages(
    question: str, messages: Sequence[tuple[str, str]]
) -> tuple[tuple[str, str], ...]:
    """질문과 관련된 턴만 골라 원래 시간순으로 평탄화한다.

    messages: `(role, text)` 메시지(오래된 것 → 최신). 마지막 턴은 점수와 무관하게 항상
    포함한다 — "그거 언제야?" 같은 지시대명사는 직전 턴이 없으면 해소되지 않고, 그 턴은
    어휘가 겹치지 않아 점수로는 늘 탈락한다.

    점수는 **마스킹 전 원문**으로 낸다: 프로세스 밖으로 나가지 않는 로컬 연산이고,
    마스킹 플레이스홀더(같은 토큰이 여러 발화에 반복된다)가 유사도를 왜곡하지 않는다.
    """
    turns = _group_turns(messages)
    if not turns:
        return ()

    question_grams = _bigrams(question)
    # 마지막 턴은 무조건, 나머지는 점수 상위 순으로 상한까지. 동점이면 최신이 이긴다
    # (정렬 키에 인덱스를 함께 넣어 내림차순).
    scored = sorted(
        (
            (_jaccard(question_grams, _bigrams(_turn_text(turn))), index)
            for index, turn in enumerate(turns[:-1])
        ),
        reverse=True,
    )
    chosen = {len(turns) - 1}
    chosen.update(index for score, index in scored[: HISTORY_INJECT_TURNS - 1] if score > 0)

    return tuple(
        message for index, turn in enumerate(turns) if index in chosen for message in turn
    )


def _group_turns(
    messages: Sequence[tuple[str, str]],
) -> tuple[tuple[tuple[str, str], ...], ...]:
    """메시지를 턴으로 묶는다 — user 발화가 새 턴을 열고 뒤따르는 assistant가 같은 턴.

    선두가 assistant인 경우(복원 상한에 걸려 질문이 잘린 대화)는 그것들끼리 첫 턴으로
    둔다. 연속 user(되묻기 뒤 재질문)는 각각 새 턴이라 페어링이 어긋나지 않는다.
    본문이 빈 메시지는 묶기 전에 버린다 — 맥락 0, 토큰만 먹는다.
    """
    turns: list[list[tuple[str, str]]] = []
    for role, content in messages:
        if not content.strip():
            continue
        if role == "user" or not turns:
            turns.append([(role, content)])
        else:
            turns[-1].append((role, content))
    return tuple(tuple(turn) for turn in turns)


def _turn_text(turn: Sequence[tuple[str, str]]) -> str:
    return " ".join(content for _role, content in turn)


def _bigrams(text: str) -> frozenset[str]:
    """공백·문장부호를 뺀 문자 2-그램 집합. 한국어는 형태소 분석 없이도 이 정도면 갈린다.

    부호를 빼는 이유: 물음표·마침표를 남기면 "…어?"처럼 어미+부호가 모든 발화에서 겹쳐
    무관한 턴도 점수를 얻는다(띄어쓰기도 같은 이유로 무시 — 표기 흔들림에 둔감해진다).
    """
    compact = re.sub(r"\W", "", text)
    if len(compact) < _MIN_BIGRAM_LEN:
        return frozenset()
    return frozenset(compact[i : i + 2] for i in range(len(compact) - 1))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
