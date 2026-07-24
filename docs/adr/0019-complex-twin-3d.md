# ADR-0019: 단지 3D 트윈 — deck.gl + JSONB geometry, 기존 세대·명부 재사용

- 상태: Accepted
- 날짜: 2026-07-24
- 관련: [00 §3.8 FR-TWIN](../00-requirements.md) · [03 §4.8](../03-database-design.md) · [01 §13](../01-architecture.md) · [09 §8.11](../09-implementation-harness.md) · [ADR-0010](0010-envelope-encryption-env-master-key.md)(PII) · [ADR-0017](0017-tenant-code-registry.md)(범용 설계 전례)

## 맥락

별도 프로토타입(AI_digitaltwin_apartment repo — 첫마을 4단지 5개 동 322세대, SQLite+FastAPI+deck.gl)이
세대 단위 3D 폴리곤(shapefile → `units.json`)과 합성 페르소나(890명)를 만들었다. 이를 LIVIQ 제품 기능
"단지 트윈"으로 흡수한다 — web-admin에서 동/호 3D 시각화 + 세대별 상태(입주·민원·관리비·설비)를 한눈에.

제약·발견:

- **파일럿 tenant가 이미 첫마을 4단지다** — `buildings`(401~405동)·`households`(322세대)는 H7-7 시드,
  세대원 명부 892건(페르소나 유래)은 H7-9 명부 업로드로 **이미 LIVIQ에 존재**한다. 없는 것은 geometry뿐.
- geometry 생성(shapefile 세대 분할 — 판상 수직 절단·보로노이·Y자 방위각 매핑)은 지리 연산(geopandas·shapely)
  의존의 오프라인 파이프라인이다. 단지마다 1회 실행되는 성격이라 서비스 런타임에 넣을 이유가 없다.
- 개인정보 절대 규칙(2·6): 명부 실명은 pii_vault 봉투 암호화, LLM 전송 금지, 위험 출력 사람 검수.
- tenant 격리(규칙 3): 신규 테이블도 RLS + composite FK 이중 방어.

## 결정

**세대 3D geometry만 신규 테이블(`household_geometries`, JSONB)로 추가하고, 나머지(세대·세대원·상태)는
전부 기존 테이블을 재사용한다. 시각화는 deck.gl 3D를 web-admin `/twin` 라우트에 dynamic import로 얹는다.**

1. **geometry 저장 = JSONB, PostGIS 미도입.** 폴리곤은 렌더링 전용이다 — 공간 쿼리(교차·거리·색인)가 없다.
   `units.json`의 `polygon_2d`/`polygon_3d`/`base_z`/`floor_height`를 그대로 보존(재계산 없음).
2. **geometry 생성 파이프라인은 LIVIQ 밖.** LIVIQ는 산출물 `units.json`의 업로드 계약만 소유한다
   (`POST /admin/twin/geometry` — (동·층·호) 매칭 검증 리포트, 재업로드=전체 교체). 프로토타입 repo의
   `generate_units.py`는 이식하지 않는다.
3. **신규 명부 테이블 없음.** 세대원 = 기존 명부(`users` status `pre_registered`(미가입)·`pending`·`active`
   + `household_id`), 성명은 pii_vault·화면 표시는 마스킹(H7-9 명부 목록과 동일 규칙). 입주(occupancy)
   오버레이도 명부 인원 집계다.
4. **범용 기능.** geometry 있는 tenant만 트윈 메뉴 노출(`GET /me`에 `has_twin` — 상태 단일 출처 유지).
   첫마을 4단지는 첫 사례일 뿐 하드코딩 없음.
5. **AI 미연동.** 트윈은 조회 화면이다 — 세대·개인 단위 데이터를 LLM에 보내지 않는다(규칙 2).
   동/단지 집계의 AI 도구 노출은 수요 확인 후 백로그.

## 대안

- **PostGIS geometry 컬럼** — 공간 쿼리 수요가 없는데 확장 설치·마이그레이션·운영 부담만 추가. JSONB로 충분,
  공간 연산 수요가 생기면 그때 승격(2단계 마이그레이션 가능).
- **households에 geometry 컬럼 직접 추가** — 322행×폴리곤 JSONB가 핵심 마스터 테이블을 비대화하고,
  세대 CRUD(H8-5)·명부 조회가 매번 무거운 컬럼을 지나게 됨. 1:1 분리 테이블이 조회 경계가 깨끗하다.
- **세대원 전용 테이블(household_members) 신설** — 명부(users)와 사람 데이터 중복(이름 vault 이중 저장,
  가입 시 소진 동기화 문제). 기존 명부가 이미 세대원 전원을 커버(892건)하므로 불필요. 페르소나의 부가
  정보(차량·관계·직업)는 현 화면 요구에 없어 백로그(수요 확인 후 별도 설계).
- **2D 동/호 그리드 먼저** — 인터뷰에서 deck.gl 3D 직행 확정(2026-07-24). 그리드는 만들지 않는다.
- **VWorld 실사 3D** — 외부 타일 서버·API 키 의존. deck.gl 단독 뷰 안정화 후 재검토(백로그).

## 결과

- 이득: 신규 테이블 1개·업로드 API 1개로 끝나는 얇은 데이터 계층. 명부·민원·관리비·설비가 그대로
  오버레이 데이터 소스가 됨. 다음 단지는 units.json 업로드만으로 트윈 활성화.
- 비용: deck.gl 의존(무거움 — 트윈 라우트 한정 dynamic import, 타 페이지 번들 무영향).
  geometry 응답(322 폴리곤, 수백 KB)은 정적 — 클라이언트 1회 로드.
- 후속: ① H9-1 데이터 계층+3D 뷰+입주 오버레이 ② H9-2 오버레이 3종(민원·관리비·설비(동 단위))+세대
  상세 패널. 설비 오버레이는 `facilities.location` 문자열≈동명 매칭의 한계를 가진 동 단위 tint —
  설비-세대 정식 매핑은 재료(배치도·설비 위치 정규화)가 생기면 재설계.
- 재검토 신호: 공간 쿼리 수요(PostGIS 승격) · 페르소나 부가정보 화면 수요(세대원 확장 테이블) ·
  트윈 집계 AI 도구 수요 · 다단지 실사 지형 요구(VWorld).
