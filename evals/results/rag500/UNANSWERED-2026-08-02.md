# 무응답 케이스 기록 — dev 전량 측정 (2026-08-02, R35)

> 목표: v2 349 + graphrag 92 전 케이스를 dev API(`POST /assistant/ask`, 세션 쿠키 — 화면과 동일 경로)로
> 측정, **answered 기대 332건 중 "답변 + 출처 ≥1" 비율 ≥95%(≥316건)**.
> 결과: **미달 — 69.6% (231/332)**. 본 문서는 요구사항 "그래도 응답이 없으면 별도 문서에 기록"의 산출물.

## 판정 요약

| 단계 | 결과 |
|---|---|
| 전량 1회 (r1) | 214/332 = 64.5% (v2 153/245 · graphrag 61/87) |
| 실패 118건 재실행 1회 | +17 회복 → **231/332 = 69.6%** |
| 노브 튜닝 | **미실시 — 조기 종료 규칙 적용** (아래 근거) |
| hard_fail | 0 (전 회차) |
| **출처율** | **100%** — 실답변 전건 출처 ≥1 (인용 파이프라인 fail-closed: 근거 없으면 답변이 아니라 폴백이 나감) |

## 노브 튜닝을 실시하지 않은 근거

1. **축 소진 기판정**: top_k·컨텍스트 예산·confidence 축은 H15-2 R1~R21에서 소진 판정 —
   정답 청크가 유사도 1위인데 모델이 `[n]`을 붙이지 않아 폐기되는 것이 상한(프롬프트 강화·사후
   재요청 모두 실측 기각, [MEASUREMENT-LOG](MEASUREMENT-LOG.md) R21).
2. **실패 구조가 노브 비의존**: 잔존 101건 = 인용 폐기 58 + 도구 인자/결과 실패 25 + clarify 도피 16 +
   도구 미호출 2. 4개 모드 전부 검색 품질이 아니라 8B 모델의 도구·인용 규율 문제 — 노브가 닿지 않는다.
3. confidence 임계 하향은 무효 — 실패가 `low_confidence`가 아니라 `no_evidence`(인용 자체가 없어
   임계 이전 단계에서 폐기)이기 때문.

**결론: 95% 응답률은 8B(llama3.1) 파일럿의 모델 티어 상한 밖이다.** R25 실측에서 같은 자산으로
14B 전환 시 인용 81→96%로 상승 — 격차 해소는 상위 모델 축(OpenAI 키 대기 중)의 몫.

## 잔존 실패 101건 — 모드별 원인·시도한 조치

공통 시도: ①전량 측정 1회 ②실패건 전량 재실행 1회(temperature 0.2 샘플링 변동 활용, 폴백은 캐시
안 되므로 실 재계산). 모드별 원인:

- **A. 인용 폐기(58)**: search_documents가 근거를 회수했으나 모델이 답변에 `[n]` 마커를 붙이지 않아
  검증 단계에서 폐기(규칙 1 — 틀린 인용은 폴백보다 나쁘다). 관리규약 조항·회의록·지침 등
  추상 질의에 집중.
- **B. 도구 카드 없음(25)**: 도구는 호출됐으나 인자 오류·빈 결과로 카드가 안 나옴(get_fees 기간
  해석, find_in_floor_plan 기기명, search_facility_graph 질의어 등).
- **C. clarify 도피(16)**: 답할 수 있는 질문에 되묻기로 이탈(R31~R32에서 6%대로 억제했으나 잔존).
- **D. 도구 미호출(2)**: 라우팅 실패 — 도구 없이 직답 시도 후 근거 없음 폴백.

### A. 검색 후 인용 폐기 (no_evidence) — 58건

| 케이스 | 카테고리 | 질문 | 증상 |
|---|---|---|---|
| V2-QA-0001 | 관리규약 조항 | 승강기는 전용부분인가요, 공용부분인가요? → 지하주차장은요? | tools=ask_clarification\|search_documents\|search_documents |
| V2-QA-0002 | 관리규약 조항 | 규약에서 입주자와 사용자는 어떻게 다른가요? | tools=search_documents |
| V2-QA-0003 | 관리규약 조항 | 한 세대가 의결권을 몇 개 가지나요? → 공유 세대는 어떻게 하나요? | tools=search_documents\|search_documents |
| V2-QA-0005 | 관리규약 조항 | 우리 집 누수로 아랫집에 피해를 줬는데 책임은 어떻게 되나요? | tools=search_documents |
| V2-QA-0008 | 관리규약 조항 | 동별 대표자 임기는 몇 년인가요? | tools=search_documents |
| V2-QA-0009 | 관리규약 조항 | 입주자대표회의 임원은 어떻게 구성되나요? | tools=search_documents |
| V2-QA-0010 | 관리규약 조항 | 동별 대표자가 사퇴하면 언제까지 다시 뽑아야 하나요? | tools=search_documents |
| V2-QA-0011 | 관리규약 조항 | 입주자대표회의 정기회의는 얼마나 자주 열리나요? → 임시회의는 언제 열리나요? | tools=search_documents\|search_documents |
| V2-QA-0012 | 관리규약 조항 | 입주민이 입주자대표회의를 방청할 수 있나요? | tools=search_documents |
| V2-QA-0014 | 관리규약 조항 | 일반 입주민도 회의 안건을 제안할 수 있나요? | tools=search_documents |
| V2-QA-0019 | 관리규약 조항 | 입주민에게는 어떤 권리가 있나요? | tools=search_documents |
| V2-QA-0020 | 관리규약 조항 | 동별 대표자는 어떤 경우에 해임되나요? → 해임 절차는요? | tools=search_documents\|search_documents |
| V2-QA-0021 | 관리규약 조항 | 동별 대표자 선출공고는 언제까지 해야 하나요? | tools=search_documents |
| V2-QA-0024 | 관리규약 조항 | 규약의 관리대상물은 어디에 정해져 있나요? | tools=search_documents |
| V2-QA-0027 | 관리규약 조항 | 집을 새로 산 사람에게도 규약이 적용되나요? | tools=search_documents |
| V2-QA-0029 | 관리규약 조항 | 입주자대표회의 의결은 어떤 방법으로 하나요? | tools=search_documents\|search_documents |
| V2-QA-0030 | 관리규약 조항 | 한번 의결된 사항을 다시 심의할 수 있나요? | tools=search_documents |
| V2-QA-0032 | 관리규약 조항 | 전자투표로도 의사결정을 할 수 있나요? | tools=search_documents\|search_similar_inquiries |
| V2-QA-0033 | 관리규약 조항 | 입주자대표회의 임원이 다른 직을 겸할 수 있나요? | tools=search_documents |
| V2-QA-0034 | 관리규약 조항 | 입주자대표회의의 의무와 책임은 무엇인가요? | tools=search_documents |
| V2-QA-0035 | 관리규약 조항 | 부녀회 같은 공동체 단체 지원 규정이 있나요? | tools=search_documents |
| V2-QA-0038 | 지침·매뉴얼 | 승강기 점검에서 지적사항이 나오면 어떻게 조치하나요? | tools=search_documents\|search_documents |
| V2-QA-0040 | 지침·매뉴얼 | 승강기 비상 연락처 게시 규정이 있나요? | tools=search_documents |
| V2-QA-0044 | 지침·매뉴얼 | 지하주차장 일산화탄소 농도가 높아지면 어떻게 하나요? | tools=search_documents |
| V2-QA-0045 | 지침·매뉴얼 | 심야 시간대 환기팬 운전 기준은요? | tools=search_documents |
| V2-QA-0053 | 지침·매뉴얼 | 급탕 중단이 필요한 정비는 언제 공지하나요? | tools=search_documents |
| V2-QA-0054 | 지침·매뉴얼 | 난방 공급 온도는 어떻게 정하나요? | tools=search_documents |
| V2-QA-0056 | 지침·매뉴얼 | 저수조 청소 후에는 뭘 확인하나요? | tools=search_documents |
| V2-QA-0057 | 지침·매뉴얼 | 저수조 월간 위생 점검 항목은요? | tools=search_documents |
| V2-QA-0061 | 지침·매뉴얼 | 화재수신기 예비 전원 시험은 얼마나 자주 하나요? | tools=search_documents |
| V2-QA-0066 | 지침·매뉴얼 | 다목적실 예약은 언제부터 할 수 있나요? | tools=search_documents |
| V2-QA-0071 | 회의록 | 2024년 10월 회의에서 승강기 주로프 교체는 어떻게 결정됐나요? | tools=search_documents |
| V2-QA-0073 | 회의록 | 2026년도 관리비 예산은 어떻게 승인됐나요? | tools=search_documents\|search_documents |
| V2-QA-0077 | 회의록 | 부스터펌프 교체는 어떻게 의결됐나요? | tools=search_documents |
| V2-QA-0078 | 회의록 | 전기차 충전구역 규약 개정 내용이 뭔가요? | tools=search_documents |
| V2-QA-0079 | 회의록 | 알뜰장터 재계약 조건은 어떻게 정해졌나요? | tools=search_documents |
| V2-QA-0081 | 회의록 | EV충전기 증설은 어떻게 의결됐나요? | tools=search_documents |
| V2-QA-0083 | 회의록 | 지하주차장 LED 잔여 구간 교체 의결 내용은요? | tools=search_documents |
| V2-QA-0085 | 회의록 | 하절기 공용전기 절감 방안으로 뭐가 의결됐나요? | tools=search_documents |
| V2-QA-0086 | 회의록 | 커뮤니티 프로그램 하반기 개편 내용은요? | tools=search_documents |
| V2-QA-0087 | 회의록 | 2024년 9월 회의에서 재활용품 매각 계약은 어떻게 논의됐나요? | tools=search_documents |
| V2-QA-0089 | 회의록 | 2024년 12월 회의에서 소방 지적사항 보수는 어떻게 처리하기로 했나요? | tools=search_documents |
| V2-QA-0092 | 회의록 | 2025년 3월 회의에서 놀이터 모래 관련 의결 내용은요? | tools=search_documents |
| V2-QA-0093 | 회의록 | 2025년 4월 회의에서 승강기 유지관리 방식은 어떻게 검토됐나요? | tools=search_documents |
| V2-QA-0098 | 회의록 | 2025년 9월 회의에서 경비용역 계약은 어떻게 하기로 했나요? | tools=search_documents |
| V2-QA-0103 | 공지 | 6월 입주자대표회의 결과 공지 내용을 알려주세요. | tools=search_documents |
| V2-QA-0107 | 공지 | 수목소독은 언제 하고 뭘 주의해야 하나요? | tools=search_documents |
| V2-QA-0135 | 관리비 | 가장 최근에 나온 관리비가 얼마인가요? | tools=get_fees\|search_documents\|search_documents\|search_documents |
| V2-QA-0146 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees\|search_documents |
| V2-QA-0191 | 시설·설비 | 단지 엘리베이터 대수를 알려주세요. | tools=search_documents |
| V2-QA-0195 | 시설·설비 | 물 관련 설비 목록을 보여주세요. | tools=search_documents |
| V2-QA-0335 | 지침·매뉴얼 | 어린이놀이터 이용 시간이랑 사용료 알려주세요. | tools=search_documents |
| V2-QA-0336 | 지침·매뉴얼 | 주민공동시설 이용 시간을 알려주세요. | tools=search_documents |
| V2-QA-0340 | 관리규약 조항 | 6월 관리비가 얼마 나왔는지 알려줘. → 전기요금은 얼마나 포함돼 있어? → 동별 대표자는 한 번 뽑히면 몇 년 동안 하나요? | tools=get_fees\|get_fees\|search_documents |
| V2-GR-0009 | 시설·설비 | 화재수신반 중계기 통신 불량이 있었나요? 원인과 조치가 궁금합니다. | tools=search_documents |
| V2-GR-0010 | 시설·설비 | 화재수신반 중계기 통신 불량이 있었나요? 원인과 조치가 궁금합니다. | tools=search_documents |
| IQ-09 | 복합·라우팅 | 층간소음 생활규칙에서 밤에 금지되는 행위가 뭔가요? | tools=search_documents |
| CL-N1 | 대화·되묻기 | 이번 달 우리 집 관리비 총액이 얼마인가요? | tools=get_fees\|search_documents\|search_documents\|search_documents |

### B. 도구 호출됐으나 카드 없음 (no_evidence) — 25건

| 케이스 | 카테고리 | 질문 | 증상 |
|---|---|---|---|
| V2-QA-0016 | 관리규약 조항 | 경비원에게 폭언하는 입주민은 어떻게 되나요? | tools=search_similar_inquiries |
| V2-QA-0025 | 관리규약 조항 | 입주자대표회의와 관리기구는 어디에 두나요? | tools=find_in_floor_plan |
| V2-QA-0047 | 지침·매뉴얼 | 정전 작업 공지는 언제 해야 하나요? | tools=get_recent_notices |
| V2-QA-0069 | 지침·매뉴얼 | 제가 찍힌 CCTV 영상을 볼 수 있나요? | tools=find_in_floor_plan |
| V2-QA-0118 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees |
| V2-QA-0122 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees |
| V2-QA-0126 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees |
| V2-QA-0134 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees |
| V2-QA-0142 | 관리비 | 3월 관리비 총액을 알려주세요. | tools=get_fees |
| V2-QA-0198 | 시설·설비 | 지금 고장 난 설비가 있나요? | tools=search_facility_graph |
| V2-QA-0207 | 시설·설비 | 점검이 임박한 설비를 알려주세요. | tools=get_overdue_checks |
| V2-QA-0208 | 시설·설비 | 이번 주에 점검해야 할 설비가 있나요? | tools=get_overdue_checks\|get_facilities\|get_facilities\|get_facilities |
| V2-QA-0211 | 시설·설비 | 점검 예정 설비 목록을 알려주세요. | tools=get_facilities |
| V2-QA-0213 | 시설·설비 | 점검 스케줄에서 초과된 건이 있나요? | tools=get_overdue_checks |
| V2-QA-0215 | 시설·설비 | 점검 기한 관리 상태가 어떤가요? | tools=get_facilities |
| V2-QA-0216 | 시설·설비 | 승강기에서 덜컹거리는 소음이 나는데, 과거에 비슷한 장애가 있었나요? | tools=search_facility_graph |
| V2-QA-0242 | 평면도 | 베란다에 콘센트가 있나요? | tools=find_in_floor_plan |
| V2-GR-0022 | 시설·설비 | 화장실 수도가 약한데 급수 설비에 이력이 있나요? | tools=search_similar_inquiries |
| V2-GR-0023 | 시설·설비 | 온수가 시원찮아요. 난방 설비에 과거 문제가 있었나요? | tools=trace_home_device_issue |
| V2-GR-0028 | 시설·설비 | 거실 콘센트가 안 돼요. 연결된 전기 설비에 장애 이력이 있나요? | tools=trace_home_device_issue\|find_in_floor_plan\|search_similar_inquiries\|get_recent_notices |
| V2-GR-0029 | 시설·설비 | 세대 분전함과 연결된 설비에 과거 문제가 있었나요? | tools=trace_home_device_issue |
| CX-R03 | 복합·라우팅 | 가까운 빈 주차자리 알려주고, 이번 달 관리비 얼마 나왔는지도 알려줘. | tools=find_nearest_available_parking\|get_fees |
| CX-M08 | 복합·라우팅 | CCTV 장애 이력 원인이랑, CCTV 설비가 몇 대인지도 알려줘. | tools=search_facility_graph\|get_facilities |
| GC-03 | 복합·라우팅 | 화재수신반 통신 불량이 반복돼요. 진짜 원인이 뭔가요? | tools=search_facility_graph |
| IQ-06 | 복합·라우팅 | 현관 도어록 건전지 경고음이 계속 울려요. | tools=trace_home_device_issue |

### C. 되묻기(clarify) 도피 — 16건

| 케이스 | 카테고리 | 질문 | 증상 |
|---|---|---|---|
| V2-QA-0004 | 관리규약 조항 | 관리사무소가 점검하러 우리 집에 들어오겠다는데 거부할 수 있나요? | clarify |
| V2-QA-0006 | 관리규약 조항 | 전에 살던 사람이 밀린 관리비는 누가 내야 하나요? | clarify |
| V2-QA-0007 | 관리규약 조항 | 동별 대표자는 총 몇 명을 뽑나요? → 우리 동 세대수는요? | clarify |
| V2-QA-0017 | 관리규약 조항 | 관리사무소 직원에게 업무 외 지시를 해도 되나요? | clarify |
| V2-QA-0018 | 관리규약 조항 | 입주하면 입주자 명부를 제출해야 하나요? | clarify |
| V2-QA-0067 | 지침·매뉴얼 | 커뮤니티동에 반려동물을 데려가도 되나요? | clarify |
| V2-QA-0108 | 공지 | 수목소독 때 반려동물 산책해도 되나요? | clarify |
| V2-QA-0231 | 평면도 | 에어컨 설치하려는데 배관이 어디에 있나요? → 안방에도 있나요? | clarify |
| V2-QA-0235 | 평면도 | 난방 온도조절기 위치를 알려주세요. | clarify |
| V2-QA-0236 | 평면도 | 각 방 온도조절기가 어디 있나요? | clarify |
| V2-QA-0245 | 평면도 | 작은방에 에어컨 배관이 있는지 확인해 주세요. | clarify |
| V2-QA-0341 | 관리규약 조항 | 6월 고지서 총액이 얼마였죠? → 지난달이랑 차이가 큰가요? → 아랫집 천장에 물이 새서 피해가 생겼는데 제가 물어줘야 하나요? | clarify |
| V2-GR-0026 | 시설·설비 | 우리 집 인터넷이 자꾸 끊겨요. 통신 관련 설비에 문제가 있었나요? | clarify |
| PK-09 | 복합·라우팅 | 지하주차장에 빈 데 있나? | clarify |
| IQ-01 | 복합·라우팅 | 월패드 버튼을 눌러도 반응이 없어요. | clarify |
| IQ-02 | 복합·라우팅 | 아랫집인데 층간소음이 심해요. | clarify |

### D. 도구 미호출 — 2건

| 케이스 | 카테고리 | 질문 | 증상 |
|---|---|---|---|
| PK-06 | 복합·라우팅 | 빈 주차자리 가까운 순으로 알려줘. | 도구 미호출 |
| PK-10 | 복합·라우팅 | 가까운 주차 자리 좀 찾아줘. | 도구 미호출 |

---

# 개정 (R35b) — 노브·모델 튜닝 라운드 결과 (사용자 DB 접근 승인 후)

초판 작성 후 사용자가 dev DB 직접 수정(1번 방식)과 **qwen 전환**을 승인해 튜닝 3라운드를 실행했다.
측정 종료 후 설정은 원복 완료(vLLM llama3.1-8b-awq · top_k 16 — 카운터 실증).

## 라운드별 결과

| 라운드 | 조치 | 결과 | 판정 |
|---|---|---|---|
| 1 | top_k 16→8 (llama) | 잔존 101건 중 24 회복(23.8%) | 재샘플링 기준선(14.4%)과 유사 — 기각 |
| 2 | **qwen3:8b 전환**(dev Ollama 23076, top_k 16) | 잔존 101건 중 **60 회복(59.4%)** | 기준선 4배 — 실질 개선 |
| 3 | qwen 전량 재측정(441건) | 아래 비교표 | 회귀 확인용 |

## llama vs qwen 전량 비교 (같은 332 분모, 각 1회)

| | llama3.1-8b-awq (vLLM) | qwen3:8b (Ollama) |
|---|---|---|
| 응답률(답변+출처≥1) | 64.5% → 누적 69.6% | **77.4%** (v2 74.3 · graphrag 86.2) |
| hard_fail | 0 | **0** (안전 게이트 전수 유지) |
| p50 지연 | 1.1s | **3.9s** |
| p95 지연 | 4.0s | **35.4s** |
| 출력 토큰(v2 전량) | 41k | **260k (6.3배)** |
| 회귀(상대가 통과한 걸 깸) | qwen 실패 75건 중 llama가 30건 성공 | llama 성공 231건 중 **27건 깸** |

- 두 모델 **합집합 상한 285/332 = 85.8%** — 완벽한 per-질문 라우터를 만들어도 95% 불가.
- qwen은 `reasoning_effort:"none"`을 Ollama가 존중해 thinking 유출 없음(R28의 Qwen3.5-vLLM 부적합과 다른 조건).
- 트레이드오프: qwen 전환 시 응답률 +7.8pp를 얻지만 p95 지연 9배·토큰 비용 6배·기존 통과 27건 회귀.

## 최종 무응답 코어 — 39건 (두 모델 · 총 5회 시도에서 전부 실패)

관리규약 조항 24 · 평면도 3 · 지침 2 · 시설 2 · 관리비(멀티턴) 2 · 기타 6.
**관리규약 조항 집중이 결정적** — 모델 불문 일관 실패는 개별 모델 상한이 아니라
"추상 조항 질의 + 인용 규율" 조합의 8B 티어 공통 한계를 가리킨다.

V2-QA-0002 ~ 0035(조항 24건) · 0047 · 0069 · 0079 · 0135 · 0207 · 0213 · 0235 · 0236 · 0245 ·
0340 · 0341 · V2-GR-0022 · IQ-06 · IQ-09 · CL-N1

## 남은 레버 (95% 도달 경로)

1. **모델 티어 상향** — R25 실측: 같은 자산 14B 전환 시 인용 81→96%. OpenAI 축(H15-2 잔여) 측정이 정공법.
2. 조항 질의 특화 처방(검색이 아니라 인용 규율이 병목이므로 프롬프트 축은 R21에서 기각됨 — 코드 처방은 별도 과제).
