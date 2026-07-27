# KTX 빈자리 모니터 — 3단계

## 이번 단계의 기능

- 선택한 열차를 일정 간격으로 반복 확인
- 조회 횟수, 경과시간, 다음 조회시간 표시
- 조회 로그 표시
- 설정한 횟수에서 연습용 빈자리 발견
- 텔레그램 알림 1회 전송
- 알림 성공 후 자동 종료
- 사용자 중지 및 결과 초기화

현재 열차와 좌석 상태는 가짜 데이터입니다.

---

## GitHub 업데이트 방법

기존 GitHub 저장소에서 다음 파일을 교체합니다.

```text
app.py
requirements.txt
README.md
.gitignore
```

Commit message 예:

```text
Add mock monitoring loop
```

Streamlit Community Cloud가 자동으로 새 버전을 배포합니다.

---

## 테스트 순서

1. 출발역 `청량리`, 도착역 `동해`를 선택합니다.
2. `연습용 열차 조회`를 누릅니다.
3. 열차 한 개를 체크합니다.
4. 조회 간격을 `5초`로 선택합니다.
5. 빈자리 발견 시점을 `3번째 조회`로 선택합니다.
6. `모니터링 시작`을 누릅니다.
7. 화면을 닫지 않고 기다립니다.
8. 세 번째 조회에서 텔레그램 메시지가 오는지 확인합니다.
9. 실행 로그에 아래 순서가 표시되는지 확인합니다.

```text
1회 매진
2회 매진
3회 빈자리 발견
3회 알림 성공
```

---

## 중요 제한

이 단계는 Streamlit 브라우저 세션이 열려 있어야 자동 실행됩니다.

브라우저를 닫아도 계속 실행되는 기능은 추후 아래 구조로 구현합니다.

```text
Streamlit 화면
    ↓
API 서버
    ↓
백그라운드 Worker
```

---

## 기존 Secrets는 그대로 유지

다음 값은 GitHub 파일에 넣지 않습니다.

```toml
TELEGRAM_BOT_TOKEN = "실제 토큰"
TELEGRAM_CHAT_ID = "실제 Chat ID"
SETUP_PIN = "관리자 PIN"
```

기존 Streamlit Community Cloud의 Secrets 설정은 파일 교체 후에도 그대로 유지됩니다.
