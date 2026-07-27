# Step 10A.2 — 3초 모니터링 + 열차별 공유 캐시

- 사용자가 저장한 3초 작업으로 실제 모니터링 시작 가능
- Worker는 작업을 3초 간격으로 처리
- 동일 열차·구간·좌석조건의 코레일 페이지 결과를 기본 30초 공유
- 같은 열차를 여러 사용자가 등록해도 브라우저 중복 실행 감소

적용 순서:

1. Supabase SQL Editor에서 `supabase_step10a2_3second_shared_cache.sql` 실행
2. Render Docker Worker 최신 Commit 배포
3. Worker 버전 `10A.2-no9A` 확인
4. Streamlit Reboot
5. 조회 간격 3초 작업 저장 후 실제 잔여석 모니터링 시작

Render 환경변수 기본값:

`KORAIL_SHARED_CACHE_SECONDS=30`
