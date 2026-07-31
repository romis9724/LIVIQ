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

## 개정 노트 (2026-07-24, H9-3 — VWorld 실사 3D 채택)

운영자 인터뷰(2026-07-24)로 **VWorld 실사 3D를 백로그에서 채택**한다. 위 "대안"에서 보류했던
VWorld를 다음 결정으로 편입:

- **렌더 스택**: 프로토타입(`AI_digitaltwin_apartment/twin/static/dashboard_vworld.html`)의 방식 그대로 —
  **Cesium**(VWorld WebGL `map.vworld.kr/js/webglMapInit.js.do`)로 실사 3D 건물 타일셋 + 우리 세대를
  Cesium Primitive로 오버레이·클리핑. deck.gl과 **별개 스택**(대체 아님).
- **deck.gl과 공존(뷰 토글)**: 기존 deck.gl 뷰(H9-1·2 오버레이·세대 상세)는 **유지**. `/twin`에 "기본
  3D(deck.gl) ↔ 실사 3D(VWorld)" 뷰 토글 추가. Cesium은 무거우므로 deck.gl과 동일하게 dynamic import 격리.
- **데이터 재배선**: 프로토타입 Cesium 코드가 부르던 프로토타입 API(`/units`·`/complaints`·`/facilities`)를
  **LIVIQ 트윈 API**(`GET /admin/twin/geometry`·`overlay`·`households/{id}`)로 교체. geometry·오버레이·세대
  상세 계약은 H9-1·2 그대로 재사용(신규 백엔드 없음 — 프런트 전용 작업).
- **API 키**: VWorld 프론트 키는 **서비스 URL(오리진) 도메인 잠금**이라 번들 노출 무방. `NEXT_PUBLIC_VWORLD_API_KEY`
  env(웹 관례 — 미설정 시 실사 뷰 비활성+안내). 실제 키는 `.env`/`.env.local`(gitignore), `.env.example`엔
  placeholder만. dev 등록 오리진 = `http://localhost:3001`(web-admin), 운영은 배포 도메인 추가 등록.
- **화면**: 프로토타입의 풀스크린 다크 몰입형이 아니라 **관리 셀 임베딩**(사이드바·헤더 유지, `/twin` 카드
  무대에 Cesium 렌더, UI 오버레이는 토큰 기반 밝은 패널 — LIVIQ 라이트 톤과 일관).
- **보안(CSP)**: 현재 web-admin은 CSP 미설정([06 §6](../06-security-privacy.md))이라 즉시 차단 요소는 없다.
  **CSP 도입 시** `script-src`·`connect-src`·`img-src`에 `https://*.vworld.kr`(map·api·타일) 허용 필요.
  프로토타입의 `document.write` 외부 스크립트 주입은 nonce CSP와 충돌 — 포팅 시 **동적 `<script>` append**로
  교체(호스트 허용). 외부 3rd-party 스크립트 로드는 트윈 실사 뷰 한정.
- **개인정보**: 실사 뷰도 조회 전용·AI 미연동. VWorld로 나가는 것은 **좌표·타일 요청뿐**(세대원·개인정보
  전송 없음 — 규칙 2). 세대 상세는 기존 마스킹 경로 재사용.
- 재검토 신호(추가): VWorld 무료 쿼터·지연 · Cesium 번들 비용 · 운영 도메인 키 갱신.

## 개정 (H9-4, 2026-07-25) — 트윈 대시보드 개편

- **메뉴**: "단지 트윈" → **"트윈 대시보드"**, 사이드바에서 **대시보드 바로 아래 같은 레벨**로 이동(hasTwin
  게이트·MANAGER 전용 유지). 트윈은 확정 데이터만 보는 운영 현황판이라 대시보드 계열로 묶는 게 자연스럽다.
- **현황 패널**: 3D 무대 옆에 LIVIQ 토큰 기반 정보 패널 — 타일 4종(총세대·입주율·미처리민원·설비이상)
  + 최근민원(6건) + 설비상태 목록. **신규 API 없음** — 총세대·입주율은 트윈 geometry/occupancy 파생,
  미처리민원·최근민원은 `GET /admin/inquiries`, 설비이상·설비상태는 `GET /admin/facilities` 재사용.
- **실사 3D 전용 컨트롤**(deck.gl엔 대응 개념 없어 실사 3D에서만 노출): 렌더 스타일(쉘/포인트/끄기)·시점
  (단지 고정/360° 회전)·렌더링(우리 단지만 clip 토글). 프로토타입 `dashboard_vworld.html`의 해당 로직을
  iframe postMessage 계약(`style`·`camera`·`clip`)으로 이식.
- **가독성 수정**: 반투명 쉘(α0.22)은 실사 건물 위에서 균일·희소 오버레이(입주 100%·관리비 균등·민원 소수)가
  시각적으로 안 보였다 → 프로토타입 **PointPrimitiveCollection**(세대 중심 도트, depth test 무시) 이식으로
  입주·민원·관리비를 포인트로 식별. 쉘/포인트 스타일 토글로 두 표현 병행.
- 백엔드·계약·개인정보 원칙 전부 불변(프런트 전용 작업).

## 개정 (H9-7, 2026-07-25) — 카메라 컨트롤은 우리가 소유한다

**실측으로 확정한 제약**: 우리 iframe 임베드에서 **Cesium 애니메이션 카메라 이동(`camera.flyTo`)이 동작하지
않는다.** 확대 버튼이 만든 비행 tween이 `startTime: undefined` 상태로 영영 시작되지 않고(유휴 시 렌더
0프레임/초, `scene.requestRender()` 강제 주입에도 카메라 0mm 이동), 그 사이 Cesium 규약대로 꺼진
`screenSpaceCameraController.enableInputs`가 완료 콜백 부재로 **복구되지 않는다**. 반면 **직접 대입
(`camera.setView`·`camera.lookAt`)은 정상**이다(실측: 궤도 거리 370m→228m 이동 성공).

**파급**: VWorld 네비게이션 위젯의 확대·축소·현재위치·초기화면은 전부 `flyTo` 기반이라 **살릴 방법이 없다**.
게다가 한 번 누를 때마다 `enableInputs=false`가 남아 **휠·드래그까지 마비**시키고, 이후 클릭은
cesium-navigation의 `if(!enableInputs) return` 가드에 막힌다(운영자가 보고한 증상의 실체).

**결정**:

- 카메라 조작은 **전부 직접 대입으로 우리가 구현**한다. iframe postMessage 계약에 `camera.cmd = "zoom"`
  (궤도 거리 배율)·`"home"`(단지 초기 시점)을 추가한다. 애니메이션은 쓰지 않는다.
- **확대·축소는 궤도 거리(`HeadingPitchRange.range`) 조절**로 표현한다 — 단지 고정을 유지한 채 거리만
  바뀌므로 확대해도 단지가 화면 중앙을 벗어나지 않는다. 현재 거리는 카메라↔기준점 실거리에서 읽어
  휠 조작과 버튼 조작이 어긋나지 않게 한다.
- **"현위치" = 단지 초기 시점 복귀**(GPS 아님). 관리 화면에서 운영자 실제 좌표로 날아가는 동작은 쓸모가 없고,
  iframe 위치 권한도 필요 없다.
- **줌 하한 150m**: 그보다 당기면 VWorld 실사 건물 타일이 저해상 지형으로 바뀌는 것이 실측됐다. 세대 쿼리를
  분간할 수 있는 한계로 150m를 택했다(하한을 올리면 "확대가 안 된다"는 인상이 남고, 없애면 실익 없이 품질만 잃는다).
- **유령 비행 정리**: 첫 화면 공개 시점에 `cancelFlight()` + `enableInputs = true`로 VWorld 인트로 비행이
  남긴 비활성 상태를 걷어낸다 — 이것만으로 휠·드래그가 되살아난다(실측).
- **죽은 위젯 버튼 4종은 CSS로 숨긴다**(확대·축소·현재위치·초기화면). 나침반·측정 도구는 손대지 않는다.
- 컨트롤 UI는 **부모 React**가 소유한다(LIVIQ 디자인 토큰 사용) — iframe은 순수 렌더라는 기존 역할 분리 유지.

**재검토 신호**: VWorld SDK 업데이트로 렌더 루프가 바뀌어 `flyTo` tween이 정상 진행되면, 위젯 버튼을 되살리고
우리 컨트롤을 걷어낼 수 있다(판정 방법: 확대 클릭 후 tween의 `startTime`이 채워지는지 확인).
