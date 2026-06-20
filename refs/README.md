# refs — 경쟁/참고 솔루션 자료

LIVIQ 기획 시 참고한 기존 아파트 관리 솔루션 소개서와, 거기서 추출한 화면 이미지를 모아둔 디렉토리.

## 원본 소개서

| 파일 | 솔루션 | 성격 | 비고 |
|------|--------|------|------|
| `aptner_introduce.pdf` | **아파트너 (Aptner)** | 입주민 모바일 앱 + 관리자 시스템 소개서 (47p) | (주)아파트너. 입주민 생활 편의 중심 |
| `info_1.pdf` | **아파트데스크 (APTDESK)** | 관리사무소 웹 자동이체·수납 관리 매뉴얼 (22p) | 회계/수납 백오피스 중심 |

## 추출 이미지

PDF 내장 비트맵을 추출한 것으로, 폰 목업·콜아웃·주석이 포함된 완성 화면 이미지다.
(`pdfimages -png`로 추출, 장식용 사진·로고·아이콘·알파마스크는 제외)

### `aptner_app/` — 아파트너 입주민 앱 화면 (20장)

접두어는 소개서의 기능 분류(A~E)를 따른다.

| 파일 | 기능 |
|------|------|
| `a-01-complaint-defect.png` | 민원·하자 접수 (처리상태 표시) |
| `a-02-visitor-vehicle-booking.png` | 방문 차량 예약 (주차관제 연동) |
| `a-03-community-center.png` | 커뮤니티센터 운영관리 (예약/정산) |
| `a-04-parking-safe-number.png` | 주차 안심번호 연결 |
| `a-05-movein-booking.png` | 입주·이사 예약 (사다리차/엘리베이터) |
| `a-06-mobile-cardkey.png` | 모바일 카드키 (S1 출입 연동) |
| `a-07-cctv.png` | 단지 CCTV 실시간 조회 |
| `a-08-electronic-vote.png` | 전자투표 (본인인증·전자서명) |
| `a-09-shuttle-bus-location.png` | 실시간 차량(셔틀/통학버스) 위치 알림 |
| `b-01-notice.png` | 아파트 공지 알림 (말머리/배지) |
| `b-02-maintenance-fee.png` | 관리비 조회 (추이 그래프·청구내역) |
| `b-03-schedule-calendar.png` | 아파트 주요 일정 캘린더 |
| `b-04-nearby-places.png` | 아파트 주변 정보(플레이스)·제휴 이벤트 |
| `c-01-resident-board.png` | 입주민 게시판(카페) |
| `c-02-council-board.png` | 입대의·선관위 전용 게시판 |
| `c-03-neighborhood-board.png` | 동네 게시판 (댓글/답글) |
| `c-04-expert-consult.png` | 전문가 상담 (법무 등) |
| `c-05-marketplace.png` | 중고마켓·나눔장터 |
| `c-06-survey.png` | 설문조사 (결과 그래프) |
| `d-01-admin-smartwork.png` | 관리자 스마트워크 (웹/태블릿/폰 목업) |

### `aptdesk_web/` — 아파트데스크 관리 웹 화면 (19장)

자동이체·수납·카드 결제 백오피스 화면. 페이지 순서대로 번호 부여.

| 파일 | 기능 |
|------|------|
| `01-autopay-application-list.png` | 자동이체 신청 내역 조회 |
| `02-monthly-applicants-search.png` | 월별 신청자 검색조건 |
| `03-monthly-applicants-result.png` | 월별 신청자 상세/요약 결과 |
| `04-duplicate-applicants.png` | 이중 신청자 조회 |
| `05-applicant-verify-request.png` | 신청자 확인 요청 |
| `06-autopay-receipt-list.png` | 자동이체 수납 내역 |
| `07-other-receipt-list.png` | 기타 수납 내역(실시간/간편결제) |
| `08-duplicate-receipt.png` | 이중 수납 확인 |
| `09-bank-branch-receipt.png` | 은행 지점 처리 수납 내역 |
| `10-aptai-payment-list.png` | 아파트아이 결제 내역 |
| `11-card-approval-list.png` | 카드 승인 내역 |
| `12-card-approval-cancel.png` | 카드 승인 취소 |
| `13-card-cancel-result.png` | 카드 승인 취소 접수 결과 |
| `14-mover-card-autopay-terminate.png` | 전출자 카드 자동이체 해지 |
| `15-card-vat-data.png` | 카드 결제대행 자료(부가세) 조회 |
| `16-card-reapproval.png` | 카드 재승인 |
| `17-card-reapproval-popup.png` | 카드 재승인 확인 팝업/결과 |
| `18-amount-edit.png` | 자동이체 금액수정 |
| `19-amount-edit-request.png` | 금액 수정 요청/결과 |

> 이 자료는 경쟁 분석·기능 벤치마킹 용도다. LIVIQ는 이들 기능 위에
> **AI 검색·응대·요약 레이어**를 얹어 차별화하는 것을 목표로 한다.
> (메인 [README](../README.md) 4·5장 참고)
