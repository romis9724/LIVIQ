-- 시나리오 6종 dev 시드(2026-08-03, 사용자 지시 — ADM-2·ADM-3 데이터 갭 보충)
-- 주의: UUID는 dev DB 실측값(테넌트 11111111-…·404동 세대·EL-402-01). 재실행 시 중복 삽입됨.
-- parts는 jsonb. incidents/maintenance_logs 직접 INSERT는 outbox를 안 남긴다 —
-- Neo4j 반영이 필요하면 outbox_events에 pending 이벤트를 함께 넣을 것(2026-08-03 적용 완료).
-- ADM-2: 이번 주 404동 민원 6건(소음 3 · 주차 2 · 설비 1, 미처리 received 2) + 지난주 소음 1건(증가 비교용)
INSERT INTO inquiries (tenant_id, household_id, author_user_id, category_code_id, title, body, status, created_at, updated_at) VALUES
('11111111-1111-1111-1111-111111111111','d6ad8924-1ade-4265-a340-01f5b7e07e94','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','978b1e8e-38cc-4129-9753-438b0a1a39fe','윗집 층간소음이 심합니다','밤 10시 이후에도 아이들 뛰는 소리가 계속됩니다. 조치 부탁드립니다.','received', now()-interval '2 days', now()-interval '2 days'),
('11111111-1111-1111-1111-111111111111','a8241aee-0612-4f98-9122-13760ca93b1b','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','a99d1408-0734-4aa9-9ab7-b0fa900fa712','지하주차장 조명 깜빡임','404동 지하 1층 엘리베이터 앞 조명이 깜빡입니다. 교체 부탁드립니다.','received', now()-interval '1 day', now()-interval '1 day'),
('11111111-1111-1111-1111-111111111111','f026bdd0-8b7e-4db5-bb65-199e2f797502','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','978b1e8e-38cc-4129-9753-438b0a1a39fe','새벽 세탁기 소음 문의','새벽 시간대 세탁기 진동 소음이 울립니다.','done', now()-interval '3 days', now()-interval '1 day'),
('11111111-1111-1111-1111-111111111111','72722c9a-b56c-4a28-bf39-b65c149b54a8','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','978b1e8e-38cc-4129-9753-438b0a1a39fe','복도 발소리 소음','늦은 밤 복도 발소리가 큽니다.','in_progress', now()-interval '2 days', now()-interval '1 day'),
('11111111-1111-1111-1111-111111111111','2bf8af5b-df0c-4dcc-afec-058e98fe998a','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','41f86cb0-dbf2-45a9-831b-67ac88533940','이중주차 반복 신고','404동 앞 이중주차가 반복됩니다.','done', now()-interval '3 days', now()-interval '2 days'),
('11111111-1111-1111-1111-111111111111','a8241aee-0612-4f98-9122-13760ca93b1b','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','41f86cb0-dbf2-45a9-831b-67ac88533940','방문차량 자리 부족','주말 방문차량 주차 공간이 부족합니다.','in_progress', now()-interval '1 day', now()-interval '1 day'),
('11111111-1111-1111-1111-111111111111','f026bdd0-8b7e-4db5-bb65-199e2f797502','b5af9e17-c8e1-40d9-98f9-c5c2d5a80beb','978b1e8e-38cc-4129-9753-438b0a1a39fe','층간소음 재발 문의','지난주에도 층간소음이 있었습니다.','done', now()-interval '9 days', now()-interval '8 days');

-- ADM-3: 402동 1호기 승강기(EL-402-01) — 최근 90일 이력 3건 + 다음 정기점검 예정일
UPDATE facilities SET next_check_at = '2026-08-10' WHERE id='518dfaee-eb7c-4953-ac01-fc1206751a6e';
INSERT INTO maintenance_logs (tenant_id, facility_id, performed_at, work, parts, performer, created_at) VALUES
('11111111-1111-1111-1111-111111111111','518dfaee-eb7c-4953-ac01-fc1206751a6e','2026-06-12','도어 센서 교체(수리)','["도어 센서 1개"]'::jsonb,'승강기 유지보수 업체', now()),
('11111111-1111-1111-1111-111111111111','518dfaee-eb7c-4953-ac01-fc1206751a6e','2026-07-01','정기점검(통과)',NULL,'승강기 유지보수 업체', now());
INSERT INTO incidents (tenant_id, facility_id, occurred_at, symptom, root_cause, resolution, created_at) VALUES
('11111111-1111-1111-1111-111111111111','518dfaee-eb7c-4953-ac01-fc1206751a6e','2026-07-18','층표시기 오류(표시 불일치)','표시기 보드 접촉 불량','보드 재장착 후 당일 복구', now());
