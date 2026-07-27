from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests
import streamlit as st


# =========================================================
# 1. 페이지 설정
# =========================================================
st.set_page_config(
    page_title="KTX 빈자리 모니터",
    page_icon="🚄",
    layout="centered",
)


# =========================================================
# 2. 역 목록
#
# 목록에 없는 역도 직접 입력할 수 있습니다.
# 다음 단계에서 공식 열차정보 API의 역 목록으로 교체할 예정입니다.
# =========================================================
STATION_NAMES = sorted(
    {
        "서울", "용산", "영등포", "광명", "수원", "평택", "천안",
        "천안아산", "아산", "온양온천", "도고온천", "신례원", "예산",
        "삽교", "홍성", "광천", "대천", "웅천", "서천", "장항",
        "군산", "대야", "행신", "대곡", "문산", "임진강", "도라산",
        "청량리", "왕십리", "상봉", "덕소", "양평", "용문", "지평",
        "가평", "강촌", "남춘천", "춘천", "서원주", "만종", "횡성",
        "둔내", "평창", "진부(오대산)", "강릉", "정동진", "묵호",
        "동해", "원주", "봉양", "제천", "단양", "풍기", "영주",
        "안동", "의성", "영천", "쌍룡", "영월", "예미", "민둥산",
        "사북", "고한", "태백", "동백산", "도계", "신기", "철암",
        "춘양", "봉화", "분천", "양원", "승부", "석포", "조치원",
        "오송", "청주", "오근장", "청주공항", "증평", "음성",
        "주덕", "충주", "삼탄", "대전", "서대전", "신탄진", "계룡",
        "논산", "강경", "함열", "공주", "익산", "김제", "신태인",
        "정읍", "백양사", "장성", "광주송정", "광주", "서광주",
        "효천", "나주", "함평", "무안", "몽탄", "일로", "임성리",
        "목포", "삼례", "전주", "임실", "오수", "남원", "곡성",
        "구례구", "순천", "여천", "여수엑스포", "벌교", "조성",
        "예당", "득량", "보성", "명봉", "이양", "능주", "화순",
        "옥천", "영동", "황간", "추풍령", "김천", "김천구미",
        "구미", "왜관", "대구", "서대구", "동대구", "경산", "청도",
        "밀양", "삼랑진", "물금", "화명", "구포", "사상", "부산",
        "진영", "창원중앙", "창원", "마산", "중리", "함안", "군북",
        "반성", "진주", "완사", "북천", "횡천", "하동", "진상",
        "광양", "부전", "센텀", "신해운대", "기장", "좌천", "남창",
        "태화강", "북울산", "울산", "경주", "서경주", "안강",
        "포항", "월포", "장사", "강구", "영덕", "점촌", "용궁",
        "개포", "예천", "상주", "함창", "하양", "아화", "건천",
        "연천", "전곡", "청산", "소요산", "동두천", "의정부",
    }
)


# =========================================================
# 3. 초기 상태
# =========================================================
def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "search_result": None,
        "search_summary": None,
        "selected_train": None,
        "monitor_active": False,
        "monitor_status": "대기",
        "monitor_check_count": 0,
        "monitor_started_at": None,
        "monitor_next_check_at": None,
        "monitor_interval": 5,
        "monitor_available_after": 3,
        "monitor_logs": [],
        "monitor_alert_sent": False,
        "monitor_last_error": "",
        "monitor_train": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_state()


# =========================================================
# 4. 공통 함수
# =========================================================
def get_secret(name: str, default: str = "") -> str:
    """Streamlit Secrets에서 값을 읽습니다."""
    try:
        value = st.secrets.get(name, default)
    except Exception:
        return default

    if value is None:
        return default

    return str(value).strip()


def make_mock_trains(
    departure_station: str,
    arrival_station: str,
    travel_date: date,
    after_hour: int,
) -> list[dict[str, Any]]:
    """연습용 가짜 열차 목록을 만듭니다."""

    base_time = datetime.combine(
        travel_date,
        datetime.min.time(),
    ).replace(hour=after_hour)

    trains: list[dict[str, Any]] = []

    for index, minutes_after in enumerate([10, 45, 90, 150], start=1):
        departure_time = base_time + timedelta(minutes=minutes_after)
        arrival_time = departure_time + timedelta(hours=2, minutes=35)

        trains.append(
            {
                "선택": False,
                "열차": "KTX",
                "열차번호": f"{100 + index}",
                "출발역": departure_station,
                "도착역": arrival_station,
                "출발시각": departure_time.strftime("%H:%M"),
                "도착시각": arrival_time.strftime("%H:%M"),
                "일반실": "매진",
                "특실": "매진",
            }
        )

    return trains


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
) -> tuple[bool, str]:
    """Telegram Bot API로 메시지를 보냅니다."""

    if not bot_token:
        return False, "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."

    if not chat_id:
        return False, "TELEGRAM_CHAT_ID가 설정되지 않았습니다."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
            },
            timeout=15,
        )
        data = response.json()
    except requests.RequestException as exc:
        return False, f"텔레그램 연결 오류: {exc}"
    except ValueError:
        return False, "텔레그램 응답을 해석하지 못했습니다."

    if response.ok and data.get("ok") is True:
        return True, "텔레그램 알림 전송 완료"

    description = data.get("description", "알 수 없는 오류")
    return False, f"전송 실패: {description}"


def get_recent_telegram_chats(
    bot_token: str,
) -> tuple[bool, list[dict[str, str]] | str]:
    """최근 봇 대화에서 Chat ID 후보를 찾습니다."""

    if not bot_token:
        return False, "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

    try:
        response = requests.get(
            url,
            params={"limit": 50, "timeout": 0},
            timeout=15,
        )
        data = response.json()
    except requests.RequestException as exc:
        return False, f"텔레그램 연결 오류: {exc}"
    except ValueError:
        return False, "텔레그램 응답을 해석하지 못했습니다."

    if not response.ok or data.get("ok") is not True:
        description = data.get("description", "알 수 없는 오류")
        return False, f"Chat ID 조회 실패: {description}"

    chats: dict[str, dict[str, str]] = {}

    for update in data.get("result", []):
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
        )
        if not message:
            continue

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", "")).strip()
        if not chat_id:
            continue

        display_name = (
            chat.get("title")
            or " ".join(
                part
                for part in [
                    chat.get("first_name", ""),
                    chat.get("last_name", ""),
                ]
                if part
            ).strip()
            or chat.get("username")
            or "이름 없음"
        )

        chats[chat_id] = {
            "Chat ID": chat_id,
            "대화 이름": display_name,
            "종류": str(chat.get("type", "")),
        }

    if not chats:
        return (
            False,
            "최근 대화가 없습니다. 텔레그램 봇에 /start를 보낸 뒤 다시 시도하세요.",
        )

    return True, list(chats.values())


def build_monitor_alert(train: dict[str, Any], check_count: int) -> str:
    """모니터링 성공 알림 문구를 만듭니다."""

    return (
        "🚨 KTX 빈자리 발견 테스트\n\n"
        f"구간: {train['출발역']} → {train['도착역']}\n"
        f"열차: {train['열차']} {train['열차번호']}\n"
        f"시간: {train['출발시각']} → {train['도착시각']}\n"
        f"조회 횟수: {check_count}회\n\n"
        "연습용 모니터링에서 좌석 발견 조건이 충족됐습니다.\n"
        "현재는 실제 코레일 좌석정보가 아닙니다."
    )


def append_monitor_log(
    check_count: int,
    result: str,
    detail: str,
) -> None:
    """모니터링 로그 한 줄을 추가합니다."""

    logs = st.session_state.monitor_logs
    logs.insert(
        0,
        {
            "확인시각": datetime.now().strftime("%H:%M:%S"),
            "조회횟수": check_count,
            "결과": result,
            "상세": detail,
        },
    )

    # 화면이 무거워지지 않도록 최근 100건만 유지합니다.
    st.session_state.monitor_logs = logs[:100]


def start_monitoring(
    interval: int,
    available_after: int,
) -> None:
    """선택된 열차로 연습용 모니터링을 시작합니다."""

    train = st.session_state.selected_train
    if not train:
        st.error("먼저 모니터링할 열차 한 개를 선택하세요.")
        return

    now = datetime.now()

    st.session_state.monitor_active = True
    st.session_state.monitor_status = "모니터링 중"
    st.session_state.monitor_check_count = 0
    st.session_state.monitor_started_at = now
    st.session_state.monitor_next_check_at = now
    st.session_state.monitor_interval = interval
    st.session_state.monitor_available_after = available_after
    st.session_state.monitor_logs = []
    st.session_state.monitor_alert_sent = False
    st.session_state.monitor_last_error = ""
    st.session_state.monitor_train = dict(train)


def stop_monitoring(reason: str = "사용자가 중지했습니다.") -> None:
    """현재 모니터링을 중지합니다."""

    if st.session_state.monitor_active:
        append_monitor_log(
            st.session_state.monitor_check_count,
            "중지",
            reason,
        )

    st.session_state.monitor_active = False
    st.session_state.monitor_status = "중지됨"
    st.session_state.monitor_next_check_at = None


def reset_monitoring() -> None:
    """모니터링 상태와 로그를 초기화합니다."""

    st.session_state.monitor_active = False
    st.session_state.monitor_status = "대기"
    st.session_state.monitor_check_count = 0
    st.session_state.monitor_started_at = None
    st.session_state.monitor_next_check_at = None
    st.session_state.monitor_logs = []
    st.session_state.monitor_alert_sent = False
    st.session_state.monitor_last_error = ""
    st.session_state.monitor_train = None


# =========================================================
# 5. 화면 상단
# =========================================================
st.title("🚄 KTX 빈자리 모니터")
st.caption("3단계 · 반복 모니터링 및 텔레그램 자동 알림 테스트")

st.info(
    "이번 단계에서는 실제 좌석 대신 가짜 좌석 상태를 반복 확인합니다. "
    "설정한 조회 횟수에 도달하면 빈자리가 생긴 것으로 가정하고 "
    "텔레그램 알림을 한 번만 전송합니다."
)


# =========================================================
# 6. 열차 조회 조건
# =========================================================
with st.form("search_form"):
    st.subheader("① 조회 조건")

    col1, col2 = st.columns(2)

    with col1:
        departure_station = st.selectbox(
            "출발역",
            options=STATION_NAMES,
            index=STATION_NAMES.index("청량리"),
            placeholder="역 이름 검색 또는 직접 입력",
            accept_new_options=True,
            help="목록에 없는 역도 직접 입력할 수 있습니다.",
        )

    with col2:
        arrival_station = st.selectbox(
            "도착역",
            options=STATION_NAMES,
            index=STATION_NAMES.index("동해"),
            placeholder="역 이름 검색 또는 직접 입력",
            accept_new_options=True,
            help="목록에 없는 역도 직접 입력할 수 있습니다.",
        )

    travel_date = st.date_input(
        "출발 날짜",
        value=date.today() + timedelta(days=1),
        min_value=date.today(),
    )

    after_hour = st.selectbox(
        "이 시간 이후 열차",
        options=list(range(24)),
        index=9,
        format_func=lambda hour: f"{hour:02d}:00 이후",
    )

    submitted = st.form_submit_button(
        "연습용 열차 조회",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.monitor_active,
    )


if submitted:
    departure_station = str(departure_station).strip()
    arrival_station = str(arrival_station).strip()

    if not departure_station or not arrival_station:
        st.error("출발역과 도착역을 모두 입력하세요.")
    elif departure_station == arrival_station:
        st.error("출발역과 도착역은 서로 달라야 합니다.")
    else:
        reset_monitoring()
        st.session_state.search_result = make_mock_trains(
            departure_station=departure_station,
            arrival_station=arrival_station,
            travel_date=travel_date,
            after_hour=after_hour,
        )
        st.session_state.search_summary = {
            "departure_station": departure_station,
            "arrival_station": arrival_station,
            "travel_date": travel_date.strftime("%Y-%m-%d"),
            "after_hour": after_hour,
        }


# =========================================================
# 7. 열차 선택
# =========================================================
if st.session_state.search_result:
    summary = st.session_state.search_summary

    st.divider()
    st.subheader("② 모니터링할 열차 선택")

    st.write(
        f"**{summary['departure_station']} → "
        f"{summary['arrival_station']}** · "
        f"{summary['travel_date']} · "
        f"{summary['after_hour']:02d}:00 이후"
    )

    result_df = pd.DataFrame(st.session_state.search_result)

    edited_df = st.data_editor(
        result_df,
        hide_index=True,
        use_container_width=True,
        disabled=[
            "열차",
            "열차번호",
            "출발역",
            "도착역",
            "출발시각",
            "도착시각",
            "일반실",
            "특실",
        ],
        column_config={
            "선택": st.column_config.CheckboxColumn(
                "선택",
                help="연습용 모니터링에 사용할 열차 한 개를 선택하세요.",
            )
        },
        key="train_table_step3",
    )

    selected_rows = edited_df[edited_df["선택"] == True]

    if st.session_state.monitor_active:
        st.warning("모니터링 중에는 열차 선택을 변경하지 마세요.")
    elif selected_rows.empty:
        st.session_state.selected_train = None
        st.warning("모니터링할 열차 한 개를 선택하세요.")
    elif len(selected_rows) > 1:
        st.session_state.selected_train = None
        st.warning("이번 단계에서는 열차 한 개만 선택할 수 있습니다.")
    else:
        selected_train = selected_rows.iloc[0].to_dict()
        st.session_state.selected_train = selected_train
        st.success(
            f"선택 완료: {selected_train['열차']} "
            f"{selected_train['열차번호']} · "
            f"{selected_train['출발시각']} 출발"
        )


# =========================================================
# 8. 모니터링 설정
# =========================================================
if st.session_state.search_result:
    st.divider()
    st.subheader("③ 연습용 모니터링 설정")

    col1, col2 = st.columns(2)

    with col1:
        monitor_interval = st.selectbox(
            "조회 간격",
            options=[5, 10, 15, 30],
            index=0,
            format_func=lambda seconds: f"{seconds}초",
            disabled=st.session_state.monitor_active,
        )

    with col2:
        available_after = st.selectbox(
            "빈자리 발견 시점",
            options=[2, 3, 5, 10],
            index=1,
            format_func=lambda count: f"{count}번째 조회",
            disabled=st.session_state.monitor_active,
            help=(
                "실제 좌석정보가 아니라, 반복 알림 기능을 확인하기 위한 "
                "연습용 조건입니다."
            ),
        )

    st.caption(
        "예: 조회 간격 5초, 빈자리 발견 시점 3번째 조회로 설정하면 "
        "약 10초 뒤 세 번째 확인에서 빈자리가 발견됩니다."
    )

    start_col, stop_col, reset_col = st.columns(3)

    with start_col:
        if st.button(
            "모니터링 시작",
            type="primary",
            use_container_width=True,
            disabled=(
                st.session_state.monitor_active
                or not st.session_state.selected_train
            ),
        ):
            start_monitoring(
                interval=monitor_interval,
                available_after=available_after,
            )
            st.rerun()

    with stop_col:
        if st.button(
            "중지",
            use_container_width=True,
            disabled=not st.session_state.monitor_active,
        ):
            stop_monitoring()
            st.rerun()

    with reset_col:
        if st.button(
            "결과 초기화",
            use_container_width=True,
            disabled=st.session_state.monitor_active,
        ):
            reset_monitoring()
            st.rerun()


# =========================================================
# 9. 자동 반복 모니터링
#
# fragment는 1초마다 화면 일부만 다시 실행합니다.
# 실제 조회는 사용자가 선택한 간격이 되었을 때만 수행합니다.
# =========================================================
@st.fragment(run_every="1s")
def monitoring_panel() -> None:
    st.divider()
    st.subheader("④ 모니터링 현황")

    status = st.session_state.monitor_status
    check_count = st.session_state.monitor_check_count
    started_at = st.session_state.monitor_started_at
    next_check_at = st.session_state.monitor_next_check_at

    now = datetime.now()

    if st.session_state.monitor_active and next_check_at is not None:
        if now >= next_check_at:
            check_count += 1
            st.session_state.monitor_check_count = check_count

            available_after = st.session_state.monitor_available_after
            train = st.session_state.monitor_train

            if check_count >= available_after:
                append_monitor_log(
                    check_count,
                    "빈자리 발견",
                    "연습용 빈자리 발견 조건 충족",
                )

                bot_token = get_secret("TELEGRAM_BOT_TOKEN")
                chat_id = get_secret("TELEGRAM_CHAT_ID")

                if not st.session_state.monitor_alert_sent:
                    success, message = send_telegram_message(
                        bot_token=bot_token,
                        chat_id=chat_id,
                        message=build_monitor_alert(train, check_count),
                    )

                    st.session_state.monitor_alert_sent = success

                    if success:
                        append_monitor_log(
                            check_count,
                            "알림 성공",
                            "텔레그램 알림 1회 전송 완료",
                        )
                        st.session_state.monitor_status = "빈자리 발견 · 알림 완료"
                    else:
                        append_monitor_log(
                            check_count,
                            "알림 실패",
                            message,
                        )
                        st.session_state.monitor_last_error = message
                        st.session_state.monitor_status = "빈자리 발견 · 알림 실패"

                st.session_state.monitor_active = False
                st.session_state.monitor_next_check_at = None

            else:
                append_monitor_log(
                    check_count,
                    "매진",
                    (
                        f"연습용 확인 결과 매진 "
                        f"({available_after}번째 조회에서 발견 예정)"
                    ),
                )
                st.session_state.monitor_next_check_at = (
                    now
                    + timedelta(
                        seconds=st.session_state.monitor_interval
                    )
                )

    status = st.session_state.monitor_status
    check_count = st.session_state.monitor_check_count
    started_at = st.session_state.monitor_started_at
    next_check_at = st.session_state.monitor_next_check_at

    elapsed_seconds = 0
    if started_at is not None:
        elapsed_seconds = max(
            0,
            int((datetime.now() - started_at).total_seconds()),
        )

    countdown = "-"
    if st.session_state.monitor_active and next_check_at is not None:
        countdown_seconds = max(
            0,
            int((next_check_at - datetime.now()).total_seconds()) + 1,
        )
        countdown = f"{countdown_seconds}초"

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("상태", status)
    metric2.metric("조회 횟수", f"{check_count}회")
    metric3.metric("다음 조회", countdown)

    st.caption(f"경과시간: {elapsed_seconds}초")

    train = st.session_state.monitor_train
    if train:
        st.write(
            f"**대상 열차:** {train['출발역']} → {train['도착역']} · "
            f"{train['열차']} {train['열차번호']} · "
            f"{train['출발시각']} 출발"
        )

    if status == "빈자리 발견 · 알림 완료":
        st.success(
            "연습용 빈자리를 발견했고 텔레그램 알림을 전송했습니다. "
            "모니터링은 자동으로 종료됐습니다."
        )
    elif status == "빈자리 발견 · 알림 실패":
        st.error(
            "빈자리는 발견했지만 텔레그램 알림 전송에 실패했습니다: "
            f"{st.session_state.monitor_last_error}"
        )
    elif st.session_state.monitor_active:
        st.info(
            "모니터링 중입니다. 이 브라우저 화면을 열어둔 상태로 기다리세요."
        )
    elif status == "대기":
        st.caption("열차를 선택하고 모니터링 시작 버튼을 누르세요.")

    logs = st.session_state.monitor_logs

    if logs:
        st.write("**실행 로그**")
        st.dataframe(
            pd.DataFrame(logs),
            hide_index=True,
            use_container_width=True,
        )


monitoring_panel()


# =========================================================
# 10. 텔레그램 연결 관리
# =========================================================
st.divider()

with st.expander("텔레그램 연결 확인 및 Chat ID 찾기"):
    bot_token = get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    setup_pin = get_secret("SETUP_PIN")

    if bot_token:
        st.success("TELEGRAM_BOT_TOKEN 등록 완료")
    else:
        st.error("TELEGRAM_BOT_TOKEN이 등록되지 않았습니다.")

    if chat_id:
        st.success("TELEGRAM_CHAT_ID 등록 완료")
    else:
        st.error("TELEGRAM_CHAT_ID가 등록되지 않았습니다.")

    entered_pin = st.text_input(
        "관리자 설정 PIN",
        type="password",
        key="step3_setup_pin",
    )

    if st.button(
        "최근 Chat ID 다시 찾기",
        use_container_width=True,
    ):
        if not setup_pin:
            st.error("Secrets에 SETUP_PIN이 없습니다.")
        elif entered_pin != setup_pin:
            st.error("관리자 설정 PIN이 일치하지 않습니다.")
        else:
            success, result = get_recent_telegram_chats(bot_token)

            if success:
                st.dataframe(
                    pd.DataFrame(result),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.error(str(result))


# =========================================================
# 11. 중요 안내
# =========================================================
st.divider()
st.warning(
    "현재 반복 조회는 브라우저 세션이 열려 있을 때만 작동합니다. "
    "브라우저를 닫아도 계속 실행되는 백그라운드 모니터링은 "
    "서버 Worker를 추가하는 후반 단계에서 구현합니다."
)

st.caption(
    "현재 버전은 실제 코레일 로그인·실시간 좌석 조회·자동 예매를 "
    "포함하지 않는 학습용 시뮬레이션입니다."
)
