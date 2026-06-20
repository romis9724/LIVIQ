# 03. 데이터베이스 설계서

> 아키텍처: [01-architecture.md](01-architecture.md) · 보안/개인정보: [06-security-privacy.md](06-security-privacy.md)
> 엔진: PostgreSQL 16 + pgvector(HNSW) · ORM: Drizzle · 모든 테이블 `snake_case`

## 1. 설계 원칙

1. **멀티테넌시**: 모든 업무 테이블에 `tenant_id`(단지) + **RLS** 강제.
2. **개인정보 분리**: 식별정보는 `pii_vault`에 분리·암호화 저장, 업무 테이블은 참조키만.
3. **불변/감사**: 핵심 행위는 `audit_logs`에 추가-only 기록.
4. **단일 출처**: 관리비 원천은 ERP. DB에는 **읽기 캐시/미러**만 두고 계산하지 않음.
5. **벡터는 본문 테이블과 분리**: `document_chunks`가 임베딩 보유.

## 2. ERD (개념)

```text
tenants(단지) 1───∞ users ───∞ user_roles
   │  1───∞ households 1───∞ users(거주)
   │  1───∞ documents 1───∞ document_chunks(vector)
   │  1───∞ conversations 1───∞ messages ───∞ citations ─► document_chunks
   │  1───∞ inquiries ──► inquiry_categories
   │  1───∞ notices 1───∞ notice_drafts
   │  1───∞ facilities 1───∞ maintenance_logs / incidents
   │  1───∞ meetings 1───1 meeting_summaries
   │  1───∞ fee_snapshots(ERP 미러)
   │  1───∞ consents / audit_logs / jobs / ai_feedback
users 1───1 pii_vault(분리·암호화)
ai_eval_golden (테넌트 공용/단지별)
```

## 3. 공통 컬럼 규약

모든 업무 테이블: `id (uuid pk)`, `tenant_id (uuid, fk→tenants)`, `created_at`, `updated_at`.
삭제는 가급적 `deleted_at`(soft delete). 개인정보 포함 테이블은 보관기간 정책 적용([06]).

## 4. 핵심 테이블

### 4.1 테넌시·계정

```sql
-- 단지
tenants(id, name, address, status, settings jsonb, created_at, updated_at)

-- 세대
households(id, tenant_id, building, unit, status, created_at, updated_at)
  UNIQUE(tenant_id, building, unit)

-- 사용자 (식별정보는 pii_vault로 분리)
users(id, tenant_id, household_id NULL, login_id, status,
      pii_ref uuid NULL,            -- pii_vault.id
      created_at, updated_at)

-- 역할 (다대다)
user_roles(id, tenant_id, user_id, role)   -- role: RESIDENT|MANAGER|STAFF|FACILITY|COUNCIL|SYS_ADMIN
  UNIQUE(user_id, role)

-- 개인정보 분리 저장 (암호화)
pii_vault(id, tenant_id, name_enc, phone_enc, email_enc,
          name_hash, phone_hash,     -- 검색용 해시(평문 저장 금지)
          created_at, updated_at)

-- 개인정보 동의
consents(id, tenant_id, user_id, purpose, granted bool, granted_at, revoked_at,
         policy_version)
```

### 4.2 문서·벡터 (RAG)

```sql
-- 원문 메타
documents(id, tenant_id, title, source_type,        -- 규약|회의록|공지|지침|매뉴얼
          visibility,                                -- ALL|RESIDENT|ADMIN|COUNCIL
          storage_key, content_hash, version,
          index_status,                              -- pending|indexing|indexed|failed
          uploaded_by, created_at, updated_at)
  UNIQUE(tenant_id, content_hash)                    -- 멱등 인제스트

-- 청크 + 임베딩
document_chunks(id, tenant_id, document_id,
                chunk_index, content text,
                heading, page int, clause,           -- 인용 정확도용 메타
                token_count int,
                embedding vector(1024),              -- 임베딩 모델 차원 고정
                created_at)
-- 인덱스
--   HNSW(embedding vector_cosine_ops)
--   btree(tenant_id, document_id)
```

> 벡터 검색은 항상 `WHERE tenant_id = $current AND visibility ∈ 허용` 선필터 후 ANN.
> 임베딩 모델/차원 변경은 마이그레이션 이벤트(전량 재색인) — 함부로 바꾸지 않음.

### 4.3 대화·인용

```sql
conversations(id, tenant_id, user_id, channel,       -- resident|admin
              created_at, updated_at)

messages(id, tenant_id, conversation_id, role,       -- user|assistant|system
         content text, intent,                        -- search|action|handoff
         confidence numeric NULL,                      -- 신뢰도
         status,                                       -- answered|fallback|handed_off
         token_input int, token_output int, cost_usd numeric,  -- [08] 비용추적
         created_at)

citations(id, tenant_id, message_id, document_id, chunk_id,
          quote text, page int, clause)                -- 응답 근거 (실재 검증됨)
```

### 4.4 민원·공지

```sql
inquiry_categories(id, tenant_id, name, default_assignee_role, sla_hours)

inquiries(id, tenant_id, household_id, author_user_id,
          category_id NULL, title, body text,
          ai_suggested_category_id NULL, ai_priority,  -- urgent|normal|low (키워드 기반)
          status,                                       -- received|assigned|in_progress|done
          assignee_user_id NULL, attachments jsonb,
          created_at, updated_at)

notices(id, tenant_id, title, body text, status,       -- draft|published
        published_at, published_by, audience,           -- ALL|building|household
        created_at, updated_at)

notice_drafts(id, tenant_id, notice_id NULL, prompt_keywords jsonb,
              ai_body text, reviewed_by NULL, review_status,  -- pending|approved|rejected
              created_at)                                      -- 자동발송 금지: 검수 후 notices로 승격
```

### 4.5 시설·회의

```sql
facilities(id, tenant_id, name, location, type, status,   -- normal|check|fault|risk
           next_check_at, created_at, updated_at)

maintenance_logs(id, tenant_id, facility_id, performed_at,
                 work text, performer, parts jsonb, created_at)

incidents(id, tenant_id, facility_id, occurred_at, symptom text,
          resolution text, root_cause text NULL, created_at)

meetings(id, tenant_id, title, held_at, audio_key NULL, created_at)
meeting_summaries(id, tenant_id, meeting_id, transcript text,
                  summary text, decisions jsonb, action_items jsonb,
                  review_status, reviewed_by, created_at)   -- 검수 후 확정
```

### 4.6 관리비 (ERP 미러, 읽기 전용)

```sql
-- ERP에서 동기화한 확정 데이터의 스냅샷. AI는 이 값을 "설명"만 함(계산 X).
fee_snapshots(id, tenant_id, household_id, period,         -- YYYY-MM
              total_amount numeric, breakdown jsonb,
              source_synced_at,                              -- ERP 동기화 시점
              created_at)
  UNIQUE(tenant_id, household_id, period)
```

### 4.7 운영·AI 품질·작업

```sql
audit_logs(id, tenant_id, actor_user_id, action, target_type, target_id,
           meta jsonb, ip, created_at)                      -- append-only

ai_feedback(id, tenant_id, message_id, rating,             -- up|down
            reason text NULL, created_at)

ai_eval_golden(id, tenant_id NULL, question text,          -- NULL=공용 골든셋
               expected_answer text, expected_doc_id NULL,
               tags jsonb, created_at)

jobs(id, tenant_id, type,                                   -- ingest|ocr|stt|reembed|eval
     ref_id, status, attempts int, error text NULL,
     created_at, updated_at)
```

## 5. RLS (행 수준 보안)

```sql
-- 모든 업무 테이블에 적용 (예: documents)
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```
- API는 트랜잭션 시작 시 `SET LOCAL app.tenant_id = $`, `app.user_id`, `app.role` 설정.
- `SYS_ADMIN`은 단지 업무 데이터 RLS를 우회하지 **않는다**(메타/모니터링 테이블만 접근). 단지 콘텐츠 열람은 별도 승인·감사 필요([06]).
- 애플리케이션 레벨 필터 + DB 레벨 RLS **이중 방어**.

## 6. 개인정보 처리

| 항목 | 정책 |
|------|------|
| 저장 | 이름·연락처·이메일은 `pii_vault`에 **암호화**. 업무 테이블은 `pii_ref`만 |
| 검색 | 평문 대신 `*_hash`(salted)로 조회 |
| 표시 | 입주민 노출 화면은 마스킹 뷰 사용 (예: `홍*동`, `010-****-1234`) |
| LLM 전송 | 호출 전 마스킹/가명화. 원문 식별정보 전송 0건 ([06], FR-AI-05) |
| 보관 | 동의 목적·기간 만료 시 파기 배치. 탈퇴 시 즉시 비식별/삭제 |
| 로그 | `audit_logs`·앱 로그에도 개인정보 비저장(마스킹) |

마스킹 뷰 예:
```sql
CREATE VIEW v_users_masked AS
SELECT u.id, u.tenant_id, u.household_id,
       mask_name(p.name_enc) AS name, mask_phone(p.phone_enc) AS phone
FROM users u LEFT JOIN pii_vault p ON p.id = u.pii_ref;
```

## 7. 인덱싱·성능

- 벡터: `document_chunks` HNSW (cosine). 검색 전 `tenant_id`·`visibility` 선필터.
- 빈번 조회: `inquiries(tenant_id, status)`, `notices(tenant_id, status, published_at)`, `fee_snapshots(tenant_id, household_id, period)`, `messages(conversation_id, created_at)`.
- `audit_logs`·`messages`는 월 단위 파티셔닝 고려(증가 대비).
- N+1 방지: 목록은 조인/배치 로드.

## 8. 마이그레이션 전략

- Drizzle 마이그레이션을 버전관리. 운영 반영은 CI에서 자동 실행([09]).
- 파괴적 변경(컬럼 삭제·임베딩 차원 변경)은 2단계(추가→백필→정리)로 무중단.
- 시드: 역할·민원 카테고리·공용 골든셋 기본 데이터.
