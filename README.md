# KTX 빈자리 모니터 — 1단계

이 프로젝트는 실제 코레일과 연결하지 않은 연습용 Streamlit 앱입니다.

## 이번 단계에서 되는 기능

- 출발역 선택
- 도착역 선택
- 날짜 선택
- 시간 선택
- 연습용 KTX 목록 표시
- 모니터링 대상 열차 체크

## 실행 방법 — Windows 명령 프롬프트

### 1. 프로젝트 폴더로 이동

```bat
cd C:\ktx-seat-monitor
```

실제 저장한 폴더 위치에 맞게 경로를 수정하세요.

### 2. 가상환경 생성

```bat
py -3.13 -m venv .venv
```

`py -3.13`이 작동하지 않으면 다음 명령을 사용하세요.

```bat
python -m venv .venv
```

### 3. 가상환경 활성화

명령 프롬프트(cmd):

```bat
.venv\Scripts\activate.bat
```

PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 필요한 프로그램 설치

```bat
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. 앱 실행

```bat
python -m streamlit run app.py
```

브라우저에서 보통 아래 주소가 자동으로 열립니다.

```text
http://localhost:8501
```

### 6. 앱 종료

명령창을 클릭한 뒤 다음 키를 누르세요.

```text
Ctrl + C
```

## 현재는 하지 않는 기능

- 코레일 로그인
- 실제 좌석 조회
- 자동 반복 조회
- 자동 예약
- 텔레그램 알림

텔레그램 알림은 2단계에서 연결합니다.
