# ADR-0016: 문서관리 게시판 전환 — 첨부 1개·버전 이력·청크 소스 일반화

- 상태: Accepted
- 날짜: 2026-07-22
- 관련: ADR-0015(공지 게시판 전환 — H8-1 브랜치에서 병행 진행 중, 머지 후 링크 연결) · [docs/03 §4.2](../03-database-design.md) · [docs/09 §8.10](../09-implementation-harness.md) · 사용자 인터뷰 확정(2026-07-22)

## 맥락

문서관리는 RAG 인제스트용 "업로드 + 색인 상태 대시보드"였다 — 본문·상세·수정 화면이 없고,
파일 교체가 불가능하며(`PATCH`는 title·visibility만), `documents.version` 컬럼은 정의만 된 유휴 상태였다.
운영자는 문서를 게시글처럼 관리하고(설명 포함), 개정판 파일을 올리면 AI 검색(벡터)이 즉시 최신본을
따라가되 이전 파일은 이력으로 남기를 원한다(2026-07-22 인터뷰).

동시에 공지(H8-1로 게시판 전환 중)도 향후 벡터화해 챗봇 검색 대상으로 삼기로 확정(H8-3 예정) —
청크 저장소가 문서 전용(`document_chunks.document_id NOT NULL`)이면 H8-3에서 또 스키마를 갈아야 한다.

제약: 절대 규칙 1(출처 인용 — 근거는 문서 원문), 규칙 3(tenant 격리 + RLS), 기존 파서가
`.pdf/.txt/.md`만 지원(HWP·OCR은 백로그), 기존 운영 데이터는 파일럿 초기 단계라 폐기 승인됨.

## 결정

문서관리를 **관리자 전용 첨부파일 게시판**으로 전환한다: 게시글 = 제목 + 본문(설명용) + **첨부 1개 필수**,
첨부 재업로드 = 새 버전 + 자동 재인제스트, 이전 파일은 버전 이력으로 보존(다운로드만), 청크 테이블은
**공지 소스까지 수용하는 `content_chunks`로 일반화**한다.

### 확정 사항 (인터뷰 2026-07-22)

| 항목 | 결정 |
|---|---|
| 노출 범위 | web-admin 전용(MANAGER·STAFF). 입주민 열람 없음 |
| 본문(body) | 설명용 텍스트(선택). **임베딩 안 함** — 벡터 인제스트는 첨부 파일만 |
| 첨부 | 게시글당 정확히 1개(필수). 허용 포맷 = 파서 지원 `.pdf/.txt/.md/.markdown`만(fail-closed 화이트리스트 — 파서 확장 시 항목만 추가) |
| 버전관리 | 재업로드 = `version + 1` + 기존 청크 삭제·재임베딩. 이력 목록 + 구 파일 다운로드만 — **롤백 없음**(필요 시 구 파일 재업로드가 곧 새 버전). 벡터는 항상 최신 버전만 |
| 삭제 | soft delete(`deleted_at`) + 청크 **즉시 삭제**(citations.chunk_id SET NULL) + answer_cache 세대 bump. MinIO 파일·버전 이력은 보존(감사 대응) |
| 기존 데이터 | 폐기 — 마이그레이션에서 documents·document_chunks 전량 삭제 후 스키마 전환(마이그레이션 로직 없음) |
| 유지 | `source_type`(카테고리) · `visibility`(AI 인용 범위) · `index_status` · reindex 엔드포인트 |

### 스키마 (docs/03 §4.2 개정)

```sql
documents(id, tenant_id, title, source_type, visibility,
          body text NULL,                 -- 게시글 본문(설명용 — 임베딩 안 함)
          version int,                    -- 현재 버전 번호(document_versions 최신과 일치)
          index_status, uploaded_by, created_at, updated_at, deleted_at)
-- storage_key·content_hash 제거 → document_versions로 이동(중복 저장 금지)

document_versions(id, tenant_id, document_id FK,
                  version int, filename, content_type, size_bytes int,
                  storage_key, content_hash, uploaded_by, created_at)
  UNIQUE(tenant_id, document_id, version)

content_chunks(id, tenant_id,
               source_type,               -- document|notice (H8-3 대비)
               document_id FK NULL, notice_id FK NULL,
               chunk_index, content, heading, page, clause, token_count,
               embedding vector(1024), created_at)
  CHECK((source_type='document') = (document_id IS NOT NULL)
        AND (source_type='notice') = (notice_id IS NOT NULL))
```

- MinIO 키: `{tenant_id}/documents/{document_id}/v{version}{suffix}` — 버전별 객체 보존.
- `citations.chunk_id` FK는 `content_chunks`로 재지정(SET NULL 유지).
- 중복 방어: DB 전역 content_hash unique는 제거(버전 이력과 양립 불가). 대신 업로드 시
  앱 레벨 검사 — 미삭제 문서들의 **현재 버전** 중 동일 해시 존재 시 409(중복 벡터·비용 방지).
  같은 문서에 현재 버전과 동일 해시 재업로드도 409(무의미한 재인제스트 방지).
- RLS: `content_chunks`·`document_versions`에 기존 tenant_isolation 정책 동일 적용.

### API 표면 (인가 전부 MANAGER·STAFF)

```text
GET    /documents                                목록(게시판)
POST   /documents                                작성 — multipart(title·source_type·visibility·body?·file 필수) → v1 + 인제스트 큐
GET    /documents/{id}                           상세 — body + 버전 이력 포함
PATCH  /documents/{id}                           메타 수정(title·body·source_type·visibility)
POST   /documents/{id}/file                      새 버전 업로드 → version+1 + 재인제스트 + 캐시 bump
GET    /documents/{id}/versions/{v}/download     버전 파일 다운로드 — API 경유 스트리밍(공지 첨부 패턴)
DELETE /documents/{id}                           soft delete + 청크 즉시 삭제 + 캐시 bump
POST   /documents/{id}/reindex                   유지
```

answer_cache 세대 bump 시점 = 검색 결과가 바뀌는 모든 곳: visibility 변경(기존) + 새 버전 업로드 + 삭제.

### H8-3(공지 벡터화) 선반영 범위

이번에 하는 것: `content_chunks` 다형 스키마(notice_id·CHECK)까지만.
이번에 안 하는 것: 공지 인제스트 경로·발행 훅·공지 청크 검색 필터 — H8-3에서 추가.
H8-3 확정 사항(기록만): 본문 항상 + 파싱 가능 첨부만 벡터화, **published만** 인제스트(draft·scheduled 제외,
발행 시점 인제스트·수정 시 재인제스트·삭제/비공개 시 청크 제거), 공지 첨부 화이트리스트(.hwp 등)는 축소 안 함.

## 대안

- **본문도 임베딩**: 소스 2개(본문+파일) 병합 청킹 복잡도 대비 이득 없음. AI 근거는 문서 원문이어야
  인용 품질 유지(절대 규칙 1). 기각.
- **hwp/docx 업로드 허용 + 색인 실패 표시**: "게시판엔 있는데 AI가 모르는 문서"를 만든다 — fail-closed
  위배. 파서 확장(백로그 HWP·OCR) 때 화이트리스트만 넓히는 쪽이 일관. 기각.
- **롤백 버튼**: 구 파일 다운로드 → 재업로드로 동일 효과. 전용 UI·상태 전이 비용만 추가(YAGNI). 기각.
- **`document_chunks` 이름 유지 + notice_id 추가**: 이름-내용 불일치로 혼란. 데이터 폐기가 승인돼
  rename 비용이 최소인 지금이 적기. 기각.
- **버전 = documents 행 복제**: 게시글 정체성(id·인용 연속성) 유지가 필요 — 별도 이력 테이블이 정규형. 기각.
- **presigned URL 다운로드**: 인가를 스토리지에 위임하게 됨 — API 경유 스트리밍(세션·tenant 이중 검증)이
  기존 성문화 패턴(ADR-0015)과 일관. 기각.

## 결과

- 이득: 운영자가 문서를 게시글로 관리(설명·개정·이력), 개정판이 AI 검색에 즉시 반영, H8-3 공지 벡터화가
  스키마 변경 없이 진입 가능.
- 비용: `document_chunks` → `content_chunks` rename 파급(ai-core 검색·citations FK·RLS·테스트),
  기존 문서 데이터 전량 폐기(승인됨 — 재업로드 필요).
- 후속: H8-3(공지 벡터화 — 다른 세션, H8-1 마감 후), HWP·OCR 파서 확장 시 화이트리스트 확대.
- 재검토 신호: 문서당 첨부 여러 개 요구가 실제로 발생하면(현재 1개 고정) document_versions를
  attachment 축으로 확장하는 별도 ADR.
