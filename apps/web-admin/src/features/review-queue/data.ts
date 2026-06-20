/** AI 검수 큐 목업 데이터 — 백엔드 연동 전 결정적 시드. */
export interface ReviewItem {
  id: string;
  asker: string;
  when: string;
  count: number;
  question: string;
  answer: string;
  confidence: number; // 0~100
  source?: { title: string; meta: string };
}

export const REVIEW_ITEMS: readonly ReviewItem[] = [
  {
    id: "rq-1",
    asker: "홍*동 입주민",
    when: "12분 전",
    count: 14,
    question: "관리비 카드 자동납부는 어떻게 신청하나요?",
    answer:
      "앱 [관리비 > 자동납부 등록] 메뉴에서 카드 등록 후 신청할 수 있는 것으로 보입니다. 등록 다음 달부터 자동 출금되며, 정확한 적용 시점은 관리사무소 확인이 필요합니다.",
    confidence: 62,
    source: { title: "관리비 납부 안내문", meta: "4페이지 · 2025.12 개정" },
  },
  {
    id: "rq-2",
    asker: "이*아 입주민",
    when: "38분 전",
    count: 6,
    question: "단지 전기차 충전 요금 단가가 정확히 얼마인가요?",
    answer:
      "충전 요금에 대한 확정 근거를 색인된 문서에서 찾지 못했습니다. 추측 답변 대신 시설 담당자 연결을 권장합니다.",
    confidence: 34,
  },
];

export interface ConfidenceLook {
  color: string;
  icon: string;
  label: string;
}

/** 신뢰도 점수 → 색/아이콘/라벨 (디자인 confStyle 이식). */
export function confidenceLook(conf: number): ConfidenceLook {
  if (conf >= 70) {
    return { color: "color-mix(in oklch, var(--color-success) 65%, var(--color-text))", icon: "✓", label: "보통" };
  }
  if (conf >= 50) {
    return { color: "color-mix(in oklch, var(--color-warning) 50%, var(--color-text))", icon: "!", label: "낮음" };
  }
  return { color: "var(--color-danger)", icon: "⚠", label: "매우 낮음" };
}
