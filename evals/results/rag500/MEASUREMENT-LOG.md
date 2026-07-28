# H15-2 측정 로그 — 설정 변화와 결과 기록

보고서 원자료. **모든 측정 실행과 환경 변화를 시간순 기록**한다. 원시 데이터(JSON)는 같은
디렉토리, 케이스 정의는 [../../fixtures/rag-validation/](../../fixtures/rag-validation/),
러너는 [../../rag500.mjs](../../rag500.mjs).

## 측정 환경 (공통)

| 구성 | 값 |
|---|---|
| api·웹 | 맥북(MacBook Pro, Apple Silicon) 로컬 스택 — 측정 실행 위치 |
| 임베딩 | **bge-m3 1024차원, 맥북 ollama — 전 측정 고정**(변인 통제) |
| 코퍼스 | 첫마을 4단지 데모 33건(#104) + RAG 검증 합성 3단지 40건 — 총 71건 indexed |
| 케이스셋 | quality-cases-500.csv (Smoke 50 · Critical 180 · Full 270) |
| 튜닝 노브 | 기본값(top_k 8 · 청크 400tok · confidence 0.8 · 출력 1024tok · timeout 60s) — 명시 변경 시 기록 |
| 채점 | 문서 단위 인용 적중 · 폴백 정확도 · Hard Gate 5종 · 완주 · TTFT/총지연 (rag500.mjs 자동) |

### 백엔드 프로필

| 라벨 | 서빙 | 모델·양자화 | 하드웨어 | 네트워크(맥북 api 기준) |
|---|---|---|---|---|
| `ollama-llama31-macbook` | ollama | llama3.1:8b (**Q4_K_M**) | 맥북 통합메모리 | localhost |
| `vllm-llama31-awq-4080ti-tunnel` | vLLM (docker vllm-openai:latest) | Meta-Llama-3.1-8B-Instruct (**AWQ INT4**) | RTX 4080 SUPER 16GB (jai1) | **SSH 터널**(공인망 왕복 포함 — 지연에 가산) |

vLLM 기동 인자: `--max-model-len 8192 --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser llama3_json`

---

## 실행 기록 (시간순)

### R1 · 2026-07-28 13:36 — ollama Smoke 50 (⚠️ 캐시 오염 — 참고용만)

- 파일: `rag500-2026-07-28T13-36-37-ollama-llama31-macbook.json`
- 설정: ollama llama3.1:8b · **답변 캐시 켜짐(TTL 3600)** — 세트 내 유사 질문이 캐시 히트
- 결과: pass 23/50(46%) · 인용 66% · 폴백정확 54% · hardfail 0 · 총지연 p50 15,569ms / p95 41,532ms · TTFT p50 28ms(캐시 히트 신호)
- **교훈: 측정은 캐시 오프 필수** → 이후 전 측정 `answer_cache_ttl_s=0`(H15-3 UI 노브). 지연 수치 무효, 품질 수치도 캐시 재생 영향 있어 R5로 대체.

### R2 · 2026-07-28 — 하드 룰 게이트, vLLM 첫 실행 (75% → 원인 규명)

- 설정: vLLM AWQ(터널) · 기존 evals 케이스
- 결과: **75%** (측정 8건 중 cite-01·readonly-03 fail — 65초 간격 3회 재현, 결정적)
- 원인 규명(백엔드 무관으로 판명):
  1. **케이스 진부화** — 데모 코퍼스 교체(#104)로 두 케이스의 전제 문서(관리규약 반려동물 조항·재활용 배출 요일)가 코퍼스에 없음. ollama에서도 동일 fail 재현으로 확인.
  2. 케이스 정비(취지 유지, 현 코퍼스 정합) 후 회복 — 커밋 `68f2293`.
- 부수 발견: **llama3.1-8b는 근거가 프롬프트에 있어도 반려동물 주제를 NO_EVIDENCE로 과잉 거부**(오케스트레이터 오프라인 재현 — 근거 블록에 답 존재 확인). 명시 수치 질문(이용 시간)은 confidence 0.847로 정상 답변. → 8B 모델 보수성의 직접 증거(품질 장 소재).

### R3 · 2026-07-28 — 게이트 재실행 (케이스 정비 후)

| 백엔드 | 결과 |
|---|---|
| ollama llama3.1:8b | **100%** (측정 10건, fail 0) |
| vLLM llama3.1-8b-AWQ | **100%** (측정 8건, fail 0 — 측정 수 차이는 rate limit로 일부 pending) |

→ **서빙 스택·양자화 차이로 인한 하드 룰(인용 규율·tool calling) 저하 없음.** vLLM `llama3_json` 파서로 구조화 tool_calls 정상.

### R4 · 2026-07-28 15:48 — vLLM Smoke 50 (캐시 오프)

- 파일: `rag500-2026-07-28T15-48-07-vllm-llama31-awq-4080ti-tunnel.json`
- 설정: vLLM AWQ(터널) · 캐시 오프 · 노브 기본값
- 결과: pass 28/50(56%) · 인용 70% · 폴백정확 62% · hardfail 1→**0**(READ_TOOLS에 `find_in_floor_plan` 누락 오탐 — 어댑터 수정 `bbf7bae`, QA-0030 재실행으로 확인) · **총지연 p50 2,251ms / p95 9,186ms** · TTFT p50 31ms
- 관측: 터널(공인망 왕복) 경유인데도 맥북 ollama 대비 지연 크게 우위. 품질도 소폭 위 — 단 양자화(AWQ vs Q4_K_M) 차이라 오차범위 가능, Critical 180에서 판별 예정.

### R5 · 2026-07-28 ~16:00 — ollama Smoke 50 (캐시 오프, R1 재측정)

- 라벨: `ollama-llama31-macbook-nocache` · 실행 중 — 완료 시 갱신

---

## 환경 변화 이벤트 (측정 결과에 영향 주는 코드·데이터 변경)

| 시점 | 변경 | 측정 영향 |
|---|---|---|
| 07-28 | **get_fees 500 수정**(breakdown 리스트 포맷 — 커밋 `38077f9`) | 관리비 카테고리 55케이스가 측정 가능해짐(수정 전엔 전건 500) |
| 07-28 | **청커 조항 마커 확장**(`[제N조]`·`Article N`) + 전량 재색인 | txt/docx/영문 문서 조항 단위 인용 성립 — 인용 적중률에 유리 |
| 07-28 | 케이스 2건 코퍼스 정합(`68f2293`) | 게이트 75%→100% (백엔드 아닌 데이터 원인) |
| 07-28 | 어댑터 READ_TOOLS 오탐 수정(`bbf7bae`) | Hard Gate 위양성 제거 |
| 07-28 | 캐시 오프 프로토콜 확립(H15-3 노브 `answer_cache_ttl_s=0`) | R1 지연 무효 판정, R4부터 적용 |

## 데이터 품질 관찰 (보고서 부록 후보)

- **PDF 개행 소실**: 첫마을 관리규약 PDF가 추출 시 개행을 잃어 여러 조항이 한 청크로 병합(거대 heading, 191청크 중 다수) — 검색 정밀도 저하 요인. 보고서에서 "문서 전처리 품질이 RAG 성능의 선행 조건" 근거.
- **모델 비결정성**: 동일 케이스(QA-0002·QA-0030)가 실행마다 인용↔폴백 반전 — temperature 0.2에서도 도구 선택 흔들림. 반복 3회 프로토콜의 근거.
- macOS→Linux 모델 전송 시 AppleDouble(`._*`) 잔재가 vLLM 기동 크래시 유발(원인 추적 기록: utf-8 decode 오류 → safetensors 글롭 오염) — 운영 절차 주의점.

## 남은 측정 계획

1. R5 완료 → ollama vs vLLM 동일 조건 Smoke 표 확정
2. Critical 180 (vLLM·ollama) — 카테고리별 품질 판별력 확보
3. 신규 모델 스크리닝(exaone3.5·qwen3 reasoning-off — 맥북 게이트 → 통과 시 4080Ti 정식)
4. 튜닝 스윕(승자 모델 1개 — top_k 4/8/16 · 청크 2값(재색인 동반))
5. **지연·동시(1·5·10)는 사내망(배포 호스트)에서 재측정** — 터널 수치는 참고
6. OpenAI 축(토요일): mini급 + 상위 1종 소규모 — 품질 상한 + 비용 실측
