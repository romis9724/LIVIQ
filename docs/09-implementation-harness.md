# 09. 구현 / 하네스 엔지니어링 가이드

> 디렉토리: [02-directory-structure.md](02-directory-structure.md) · 테스트: [07-testing-strategy.md](07-testing-strategy.md)
> 목표: **재현 가능하고 검증된 빌드**. 사람·에이전트 모두 같은 게이트를 통과한다.

## 1. 빌드 순서 (의존성 역순)

기반부터 위로 쌓는다. 각 단계는 테스트 그린 후 다음 진행.

```text
1) packages/config-ts, config-eslint, shared      ← 타입·규칙·DTO
2) packages/db (스키마·RLS·마이그레이션·시드)         ← 데이터 토대
3) packages/ai-core (pii·retrieval·budget·citations) ← AI 토대 (단위테스트 우선)
4) apps/api (auth·tenants·documents·search)        ← 인가·RLS·검색
5) apps/ai-worker (ingest·embed·ocr)               ← 인제스트 파이프라인
6) apps/api (assistant·inquiries·notices·fees …)   ← 도메인 기능
7) packages/ui (토큰·공용 컴포넌트)
8) apps/web-resident, web-admin                    ← 화면
9) tests/e2e, tests/ai-eval                        ← 여정·품질 게이트
```

> 원칙(README rules): 새 구현 전 **재사용 검토**(라이브러리·패턴), KISS/YAGNI, 작은 파일.

## 2. 개발 환경

현재 실행 가능(웹 앱 + 공유 패키지):

```bash
pnpm install
pnpm dev         # turbo run dev — web-resident, web-admin, ui 병렬
pnpm build
pnpm lint
pnpm typecheck
pnpm test
pnpm start       # build 후
```

도입 후 추가 예정(해당 패키지 도입 시 루트 스크립트로 승격):

```bash
pnpm db:migrate && pnpm db:seed   # packages/db 도입 후
pnpm e2e                          # tests/e2e 도입 후
```

- 로컬 인프라: `infra/docker-compose.yml`(작성 예정) — postgres(pgvector), redis, minio(s3), neo4j.
- env는 `.env`(로컬), `.env.example` 제공. 부팅 시 Zod 검증(누락=즉시 실패).
- 시크릿은 로컬도 평문 커밋 금지.

## 3. 코드 게이트 (로컬·CI 공통, 순서 고정)

`format → lint → typecheck → test → build` (사용자 web hooks 순서 준수).

| 단계 | 명령(예) | 차단 |
|------|----------|------|
| format | `pnpm prettier --check` | – |
| lint | `pnpm eslint` | ✅ |
| typecheck | `pnpm tsc --noEmit` | ✅ |
| unit/integration | `pnpm test --coverage` (≥80%) | ✅ |
| 보안(인가/RLS/마스킹) | 전용 스위트 | ✅ (CRITICAL) |
| e2e | `pnpm e2e` (핵심 여정) | ✅ |
| a11y | axe | ✅(심각) |
| ai-eval | 회귀 비교 | ⚠️→리뷰 |
| build | `pnpm build` | ✅ |

## 4. CI/CD (`.github/workflows`)

```text
PR:  install(turbo cache) → lint → typecheck → unit/integration(Testcontainers)
     → 보안 스위트 → build → e2e(미리보기) → a11y → ai-eval(diff)
     → 시크릿 스캔 + 의존성 취약점 스캔
merge(main): 마이그레이션 dry-run → 스테이징 배포 → 스모크 → (승인) 운영
```
- Turbo 원격 캐시로 변경 영향 패키지만 빌드/테스트(시간·비용 절감).
- 머지 차단 조건은 [07 §9](07-testing-strategy.md).

## 5. 권장 훅 (PostToolUse / Pre / Stop)

> 사용자 web hooks 규칙 기반. **레포 소유 도구만** 사용(원격 1회성 실행 금지).

- PostToolUse(Write|Edit): prettier → eslint --fix → tsc(빠른 영역)
- PreToolUse(Write): 800줄 초과 차단(파일 분할 유도)
- Stop: `pnpm build` 또는 영향 범위 빌드 검증

## 6. AI 품질 운영 루프 (배포 후)

```text
응답 로그·👎 수집 → 골든셋 후보 검토 → 골든셋 갱신 → 회귀 평가
                                          → 프롬프트/청킹/라우팅 조정 → 재평가
```
- 모델/프롬프트/임베딩 변경은 **회귀 평가 통과** 후 반영([07 §5], [08 §9]).
- 환각률·비용·폴백율 임계 초과 시 알림 → 원인 분석.

## 7. 데이터/마이그레이션 운영

- 마이그레이션은 CI 자동, 파괴적 변경은 2단계 무중단([03 §8]).
- 임베딩 차원/모델 변경 = 전량 재색인 이벤트(비용·시간 계획 필요).
- 백업·복구 리허설(개인정보 포함 → 접근통제·암호화 백업).

## 8. 단계별 구현 플랜 (README 로드맵과 정합)

| 단계 | 내용 | 종료 기준 |
|------|------|-----------|
| 0. 토대 | 모노레포·DB·RLS·ai-core 골격·CI 게이트 | 빈 앱 그린 빌드, RLS 테스트 통과 |
| 1. RAG MVP | 문서 인제스트→검색→인용 응답, 비서 화면 | 골든셋 적중률 게이트, 환각 폴백 동작 |
| 2. 입주민/관리자 | 민원·공지초안·관리비 설명·검수 큐 | E2E 여정 그린, 검수 게이트 |
| 3. 시설 | 시설 도우미(Neo4j 그래프·원인 후보) | 회귀 평가·검수 통과 |
| 4. 운영/최적화 | 대시보드·캐시·라우팅·비용 상한 | 비용/품질 대시보드, 알림 |

## 9. 정의: "완료(Done)"

기능은 다음을 **모두** 만족할 때 완료:
- [ ] 요구사항 ID 충족([00]) + 테스트(단위/통합/E2E) 그린
- [ ] 인가·테넌트 격리·개인정보 마스킹 검증
- [ ] 접근성·반응형(4 브레이크포인트) 확인
- [ ] 위험 출력 검수 게이트 동작(해당 시)
- [ ] 토큰/비용 기록·캐시 적용(해당 시)
- [ ] 문서/ADR 갱신, 코드리뷰 통과

## 10. ADR 로그

정본은 [docs/adr/](adr/README.md)다. 결정 변경 시 새 ADR을 추가하고 이전 결정은 `Superseded` 처리한다. 요약 표는 [01 §12](01-architecture.md) 참조.
