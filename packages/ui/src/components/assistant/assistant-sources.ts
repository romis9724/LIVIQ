/**
 * 출처 카드 묶기 — 같은 문서가 여러 번 뜨는 것을 막는다.
 *
 * 서버는 근거 청크마다 인용을 하나씩 보낸다([n] 번호가 청크 단위라 그래야 한다). 그래서
 * 같은 규약 문서에서 세 조항을 인용하면 화면에 같은 제목 카드가 세 장 뜬다 — 사용자에게는
 * "출처가 중복으로 많이 나온다"로 읽힌다. 번호 체계는 서버 것을 그대로 두고 **표시만** 묶는다.
 *
 * 도구 결과 카드(`documentId === null`)는 서버가 이미 (source_kind, quote)로 중복을 걸러
 * 보내므로 여기서는 제목 기준으로만 묶는다.
 */

import type { AssistantCitation } from "./assistant-events";

export interface GroupedSource {
  /** 대표 인용 번호 — 그룹에서 가장 작은 ref(키·정렬용). */
  ref: number;
  title: string;
  /** 조항·페이지 등 하위 표기. 중복 제거 후 순서 유지. */
  details: string[];
  /** 묶인 인용 수. 1이면 배지를 숨기는 쪽이 깔끔하다. */
  count: number;
}

/** 인용 1건의 하위 표기(조항 · 페이지). 둘 다 없으면 빈 문자열. */
export function citationDetail(c: AssistantCitation): string {
  return [c.clause, c.page != null ? `${c.page}p` : null].filter(Boolean).join(" · ");
}

/**
 * 같은 출처끼리 묶는다. 키는 문서면 `documentId`, 도구 카드면 제목.
 * 입력 순서(= 서버가 보낸 근거 순서)를 유지한다 — 상위 근거가 앞에 오는 게 의미 있다.
 */
export function groupCitations(citations: readonly AssistantCitation[]): GroupedSource[] {
  const groups = new Map<string, GroupedSource>();
  for (const c of citations) {
    const key = c.documentId ?? `title:${c.documentTitle}`;
    const detail = citationDetail(c);
    const found = groups.get(key);
    if (!found) {
      groups.set(key, {
        ref: c.ref,
        title: c.documentTitle,
        details: detail ? [detail] : [],
        count: 1,
      });
      continue;
    }
    // 같은 조항이 두 청크에 걸쳐 있으면 표기가 같다 — 한 번만 남긴다.
    if (detail && !found.details.includes(detail)) found.details.push(detail);
    found.count += 1;
  }
  return [...groups.values()];
}
