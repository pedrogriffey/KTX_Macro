# KTX 빈자리 모니터 — 2단계

이번 단계에서 추가되는 기능:

- 청량리, 동해 등 전국 주요 여객역 목록 확대
- 역 이름 검색
- 목록에 없는 역 직접 입력
- Telegram Bot 연결
- 선택한 열차로 테스트 메시지 전송

현재 열차와 좌석 상태는 여전히 연습용 가짜 데이터입니다.

## GitHub 파일 업데이트

기존 저장소의 다음 파일을 교체합니다.

- `app.py`
- `requirements.txt`
- `.gitignore`
- `README.md`

`.streamlit/secrets.toml.example`은 참고용이라 올려도 됩니다.
실제 `secrets.toml` 파일은 GitHub에 올리지 마세요.

## 텔레그램 봇 만들기

1. Telegram에서 `@BotFather`를 검색합니다.
2. `시작`을 누릅니다.
3. `/newbot`을 입력합니다.
4. 봇의 표시 이름을 입력합니다.
5. `bot`으로 끝나는 사용자 이름을 입력합니다.
6. BotFather가 보여주는 토큰을 복사합니다.

## Streamlit Secrets 등록

배포된 앱에서 다음 위치로 이동합니다.

```text
Manage app → Settings → Secrets
```

처음에는 다음 내용을 입력합니다.

```toml
TELEGRAM_BOT_TOKEN = "BotFather가 발급한 실제 토큰"
TELEGRAM_CHAT_ID = ""
SETUP_PIN = "본인만 아는 6자리 이상의 숫자 또는 문자"
```

## Chat ID 찾기

1. Telegram에서 만든 봇을 엽니다.
2. `시작` 또는 `/start`를 전송합니다.
3. Streamlit 앱을 새로고침합니다.
4. `처음 연결할 때: Chat ID 찾기`를 엽니다.
5. Secrets에 등록한 `SETUP_PIN`을 입력합니다.
6. `최근 Chat ID 찾기`를 누릅니다.
7. 표시된 Chat ID를 복사합니다.

## Chat ID 등록

다시 Streamlit Secrets에서 값을 추가합니다.

```toml
TELEGRAM_BOT_TOKEN = "실제 토큰"
TELEGRAM_CHAT_ID = "찾은 숫자"
SETUP_PIN = "본인PIN"
```

## 텔레그램 테스트

1. 출발역과 도착역을 선택합니다.
2. `연습용 열차 조회`를 누릅니다.
3. 열차 한 개만 체크합니다.
4. `선택한 열차로 텔레그램 테스트 알림 보내기`를 누릅니다.
5. Telegram에 메시지가 도착하는지 확인합니다.

## 역 검색

역 선택창을 누르고 `청량리` 또는 `동해`를 입력해 검색할 수 있습니다.
목록에 없는 역도 직접 입력한 뒤 선택할 수 있습니다.
