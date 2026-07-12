# ADR-0009: Neo4j를 MVP부터 포함

- 상태: Accepted
- 날짜: 2026-07-13
- 관련: [docs/01 §12](../01-architecture.md), [docs/03 §4.9](../03-database-design.md), [docs/11](../11-data-architecture.md), [docs/06 §3](../06-security-privacy.md), [docs/07](../07-testing-strategy.md), [FR-FAC-02](../00-requirements.md), [리뷰 열린질문 2](../review/cursor-review.md)

## 맥락

Neo4j는 시설 전용 파생 그래프로 설계가 완료돼 있다([01 §12] 요약·[03 §4.9]·[11]). 그러나 파일럿(90세대)은 장애·정비 이력 데이터가 아직 없어 효용이 언제 나타나는지 논쟁이 있었고(리뷰 열린질문), 도입 시점이 미결이었다. FR-FAC-02(시설 AI 도우미)는 Should인데 도구 `search_facility_graph`(FR-AI-08)는 Must라 우선순위가 모순이었다.

## 결정

**MVP부터 Neo4j를 포함**한다 — 인프라(compose)·outbox graph-sync·tenant 격리 테스트(CRITICAL)까지 초기부터 구축한다. 함께 **FR-FAC-02를 Should → Must로 승격**해 도구(Must)와의 모순을 해소한다. 아키텍처를 조기에 검증하고, 이력 데이터가 쌓이는 즉시 효용이 발생한다.

## 대안

- **Phase 2 연기**: 운영비는 절감되나 아키텍처 검증이 지연되고 그래프 전제 기능이 늦어짐. 기각(사용자 결정).
- **spike만 진행**: 검증과 운영 사이 중간 형태로 경계·게이트가 애매해짐. 기각.

## 결과

- MVP 운영 스택에 Neo4j가 추가된다(백업·모니터링 포함).
- 교차 tenant 그래프 침투·관계 tenant 불일치 거부 격리 테스트는 **머지 차단 게이트**([07](../07-testing-strategy.md)).
- 재검토 신호: 파일럿에서 시설 질의 빈도가 극히 낮으면 리소스 재배분 검토.
