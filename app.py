from __future__ import annotations

from datetime import date, datetime, timedelta
import secrets
import time
from typing import Any

import pandas as pd
import streamlit as st

from tago_api import TagoAPIError, TagoClient
from telegram_link import (
    TelegramError,
    find_chat_by_link_code,
    get_bot_profile,
    send_message,
)


# =========================================================
# 1. 페이지 설정
# =========================================================
st.set_page_config(
    page_title="KTX 빈자리 모니터",
    page_icon="🚄",
    layout="centered",
)


# =========================================================
# 2. Session State 초기화
#
# Streamlit의 Session State는 방문자 세션별로 분리됩니다.
# 따라서 다른 사용자의 열차 선택값이나 Telegram Chat ID와 섞이지 않습니다.
# 다만 새로고침/세션 종료 후에는 초기화됩니다.
# =========================================================
def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "telegram_link_code": secrets.token_urlsafe(12).replace("-", "_"),
        "telegram_chat_id": "",
        "telegram_display_name": "",
        "official_trains": None,
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
        "last_search_monotonic": 0.0,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_state()


# =========================================================
# 3. Secrets
# =========================================================
def get_secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        return default

    if value is None:
        return default

    return str(value).strip()


DATA_GO_KR_SERVICE_KEY = get_secret("DATA_GO_KR_SERVICE_KEY")
TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN")


# =========================================================
# 4. 공식 데이터 캐시
#
# 역 목록은 모든 사용자에게 동일한 공개 데이터이므로 하루 동안 공유 캐시합니다.
# 시간표는 동일 구간/날짜 요청을 60초 동안 공유해 API 호출량을 줄입니다.
# =========================================================
@st.cache_data(ttl=86400, show_spinner=False)
def load_official_stations(
    _service_key: str,
) -> list[dict[str, str]]:
    client = TagoClient(_service_key)
    return client.get_all_stations()


@st.cache_data(ttl=60, max_entries=500, show_spinner=False)
def load_official_timetable(
    departure_station_id: str,
    arrival_station_id: str,
    departure_date: str,
    _service_key: str,
) -> list[dict[str, Any]]:
    client = TagoClient(_service_key)
    return client.get_timetable(
        departure_station_id=departure_station_id,
        arrival_station_id=arrival_station_id,
        departure_date=departure_date,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def load_bot_profile(
    _bot_token: str,
) -> dict[str, Any]:
    return get_bot_profile(_bot_token)


# =========================================================
# 5. 모니터링 함수
# =========================================================
def append_monitor_log(
    check_count: int,
    result: str,
    detail: str,
) -> None:
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
    st.session_state.monitor_logs = logs[:100]


def reset_monitoring() -> None:
    st.session_state.monitor_active = False
    st.session_state.monitor_status = "대기"
    st.session_state.monitor_check_count = 0
    st.session_state.monitor_started_at = None
    st.session_state.monitor_next_check_at = None
    st.session_state.monitor_logs = []
    st.session_state.monitor_alert_sent = False
    st.session_state.monitor_last_error = ""
    st.session_state.monitor_train = None


def start_monitoring(
    interval: int,
    available_after: int,
) -> None:
    train = st.session_state.selected_train

    if not train:
        st.error("먼저 모니터링할 열차 한 개를 선택하세요.")
        return

    if not st.session_state.telegram_chat_id:
        st.error("먼저 본인의 텔레그램을 연결하세요.")
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


def stop_monitoring() -> None:
    if st.session_state.monitor_active:
        append_monitor_log(
            st.session_state.monitor_check_count,
            "중지",
            "사용자가 모니터링을 중지했습니다.",
        )

    st.session_state.monitor_active = False
    st.session_state.monitor_status = "중지됨"
    st.session_state.monitor_next_check_at = None


def build_alert_message(
    train: dict[str, Any],
    check_count: int,
) -> str:
    return (
        "🚨 KTX 빈자리 발견 테스트\n\n"
        f"구간: {train['출발역']} → {train['도착역']}\n"
        f"열차: {train['열차종류']} {train['열차번호']}\n"
        f"출발: {train['출발일시']}\n"
        f"도착: {train['도착일시']}\n"
        f"조회 횟수: {check_count}회\n\n"
        "열차와 시간은 TAGO 공식 운행 시간표입니다.\n"
        "단, 빈자리 발견은 아직 연습용 시뮬레이션입니다."
    )


# =========================================================
# 6. 상단 안내
# =========================================================
st.title("🚄 KTX 빈자리 모니터")
st.caption("4단계 · 공식 열차 시간표 + 사용자별 텔레그램 연결")

st.info(
    "열차번호와 출도착 시간은 국토교통부 TAGO 공식 열차정보 API에서 "
    "가져옵니다. 좌석 재고는 이 API가 제공하지 않으므로, "
    "빈자리 발견 부분은 아직 연습용 시뮬레이션입니다."
)

with st.expander("여러 사람이 사용할 수 있도록 바뀐 점"):
    st.write(
        "- 열차 선택, 모니터링 상태와 Telegram Chat ID는 사용자 세션별로 분리됩니다.\n"
        "- 서버에는 공공데이터 인증키와 하나의 텔레그램 봇 토큰만 저장합니다.\n"
        "- 각 사용자는 고유 연결코드로 자신의 텔레그램을 연결합니다.\n"
        "- 공식 역 목록과 시간표는 캐시해 API 사용량을 줄입니다.\n"
        "- 아직 로그인과 데이터베이스가 없어 새로고침하면 사용자 연결이 초기화됩니다."
    )


# =========================================================
# 7. 필수 서버 설정 확인
# =========================================================
missing_secrets = []

if not DATA_GO_KR_SERVICE_KEY:
    missing_secrets.append("DATA_GO_KR_SERVICE_KEY")

if not TELEGRAM_BOT_TOKEN:
    missing_secrets.append("TELEGRAM_BOT_TOKEN")

if missing_secrets:
    st.error(
        "Streamlit Secrets에 다음 값이 필요합니다: "
        + ", ".join(missing_secrets)
    )
    st.code(
        'DATA_GO_KR_SERVICE_KEY = "공공데이터포털 일반 인증키(Decoding)"\n'
        'TELEGRAM_BOT_TOKEN = "기존 BotFather 토큰"',
        language="toml",
    )
    st.stop()


# =========================================================
# 8. 사용자별 텔레그램 연결
# =========================================================
st.subheader("① 내 텔레그램 연결")

try:
    bot_profile = load_bot_profile(TELEGRAM_BOT_TOKEN)
    bot_username = str(bot_profile.get("username", "")).strip()
except TelegramError as exc:
    st.error(str(exc))
    st.stop()

if not bot_username:
    st.error("텔레그램 봇 사용자명을 확인하지 못했습니다.")
    st.stop()

if st.session_state.telegram_chat_id:
    st.success(
        f"연결 완료: {st.session_state.telegram_display_name}"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button(
            "테스트 메시지 보내기",
            use_container_width=True,
        ):
            try:
                send_message(
                    TELEGRAM_BOT_TOKEN,
                    st.session_state.telegram_chat_id,
                    (
                        "✅ KTX 빈자리 모니터 연결 완료\n\n"
                        "이 브라우저 세션의 알림이 이 대화로 전송됩니다."
                    ),
                )
                st.success("테스트 메시지를 보냈습니다.")
            except TelegramError as exc:
                st.error(str(exc))

    with col2:
        if st.button(
            "연결 해제",
            use_container_width=True,
        ):
            st.session_state.telegram_chat_id = ""
            st.session_state.telegram_display_name = ""
            st.session_state.telegram_link_code = (
                secrets.token_urlsafe(12).replace("-", "_")
            )
            st.rerun()
else:
    link_code = st.session_state.telegram_link_code
    bot_link = f"https://t.me/{bot_username}?start={link_code}"

    st.write(
        "아래 버튼을 누르고 텔레그램에서 **시작**을 누른 뒤, "
        "다시 앱으로 돌아와 연결 확인을 누르세요."
    )

    st.link_button(
        "텔레그램에서 내 알림 연결하기",
        bot_link,
        use_container_width=True,
        type="primary",
    )

    st.caption(
        f"현재 브라우저 전용 연결코드: `{link_code}`"
    )

    if st.button(
        "텔레그램 연결 확인",
        use_container_width=True,
    ):
        try:
            matched_chat = find_chat_by_link_code(
                TELEGRAM_BOT_TOKEN,
                link_code,
            )
        except TelegramError as exc:
            st.error(str(exc))
        else:
            if matched_chat is None:
                st.warning(
                    "아직 연결 메시지를 찾지 못했습니다. "
                    "텔레그램에서 시작을 누른 뒤 다시 확인하세요."
                )
            else:
                st.session_state.telegram_chat_id = matched_chat["chat_id"]
                st.session_state.telegram_display_name = (
                    matched_chat["display_name"]
                )
                st.success("본인의 텔레그램이 연결됐습니다.")
                st.rerun()


# =========================================================
# 9. 공식 역 목록 로드
# =========================================================
st.divider()
st.subheader("② 공식 열차 조회")

try:
    with st.spinner("공식 역 목록을 불러오는 중입니다..."):
        stations = load_official_stations(DATA_GO_KR_SERVICE_KEY)
except TagoAPIError as exc:
    st.error(str(exc))
    st.info(
        "공공데이터포털에서 TAGO 열차정보 활용신청이 승인됐는지, "
        "Secrets에 일반 인증키(Decoding)를 넣었는지 확인하세요."
    )
    st.stop()

station_map = {
    row["station_id"]: row
    for row in stations
}
station_ids = list(station_map.keys())


def station_label(station_id: str) -> str:
    return station_map[station_id]["display_name"]


def find_station_default(name: str) -> int:
    for index, station_id in enumerate(station_ids):
        if station_map[station_id]["station_name"] == name:
            return index
    return 0


with st.form("official_search_form"):
    col1, col2 = st.columns(2)

    with col1:
        departure_station_id = st.selectbox(
            "출발역",
            station_ids,
            index=find_station_default("청량리"),
            format_func=station_label,
        )

    with col2:
        arrival_station_id = st.selectbox(
            "도착역",
            station_ids,
            index=find_station_default("동해"),
            format_func=station_label,
        )

    travel_date = st.date_input(
        "출발 날짜",
        value=date.today() + timedelta(days=1),
        min_value=date.today(),
    )

    after_hour = st.selectbox(
        "이 시간 이후",
        list(range(24)),
        index=9,
        format_func=lambda hour: f"{hour:02d}:00 이후",
    )

    ktx_only = st.checkbox(
        "KTX 계열만 표시",
        value=True,
        help="KTX, KTX-산천, KTX-이음, KTX-청룡 등 이름에 KTX가 포함된 열차만 표시합니다.",
    )

    search_submitted = st.form_submit_button(
        "공식 열차 시간표 조회",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.monitor_active,
    )


if search_submitted:
    if departure_station_id == arrival_station_id:
        st.error("출발역과 도착역은 서로 달라야 합니다.")
    else:
        # 한 사용자가 버튼을 빠르게 반복 클릭하는 것을 제한합니다.
        elapsed = time.monotonic() - st.session_state.last_search_monotonic

        if elapsed < 3:
            st.warning("잠시 후 다시 조회하세요.")
        else:
            st.session_state.last_search_monotonic = time.monotonic()
            reset_monitoring()

            departure_station = station_map[departure_station_id]
            arrival_station = station_map[arrival_station_id]

            try:
                with st.spinner("공식 열차 시간표를 조회하는 중입니다..."):
                    rows = load_official_timetable(
                        departure_station_id,
                        arrival_station_id,
                        travel_date.strftime("%Y%m%d"),
                        DATA_GO_KR_SERVICE_KEY,
                    )
            except TagoAPIError as exc:
                st.error(str(exc))
            else:
                filtered_rows = [
                    row
                    for row in rows
                    if row["departure_dt"].hour >= after_hour
                    and (
                        not ktx_only
                        or "KTX" in row["train_type"].upper()
                    )
                ]

                table_rows = []
                for row in filtered_rows:
                    fare_text = (
                        f"{row['adult_fare']:,}원"
                        if row["adult_fare"] is not None
                        else "-"
                    )

                    table_rows.append(
                        {
                            "선택": False,
                            "열차종류": row["train_type"],
                            "열차번호": row["train_no"],
                            "출발역": (
                                row["departure_station"]
                                or departure_station["station_name"]
                            ),
                            "도착역": (
                                row["arrival_station"]
                                or arrival_station["station_name"]
                            ),
                            "출발일시": row["departure_dt"].strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            "도착일시": row["arrival_dt"].strftime(
                                "%Y-%m-%d %H:%M"
                            ),
                            "일반운임": fare_text,
                            "좌석상태": "공공 API 미제공",
                        }
                    )

                st.session_state.official_trains = table_rows
                st.session_state.search_summary = {
                    "departure_station": departure_station["station_name"],
                    "arrival_station": arrival_station["station_name"],
                    "travel_date": travel_date.strftime("%Y-%m-%d"),
                    "after_hour": after_hour,
                    "ktx_only": ktx_only,
                }
                st.session_state.selected_train = None


# =========================================================
# 10. 공식 시간표 결과 및 열차 선택
# =========================================================
if st.session_state.official_trains is not None:
    summary = st.session_state.search_summary

    st.divider()
    st.subheader("③ 모니터링할 열차 선택")

    st.write(
        f"**{summary['departure_station']} → "
        f"{summary['arrival_station']}** · "
        f"{summary['travel_date']} · "
        f"{summary['after_hour']:02d}:00 이후"
    )

    if not st.session_state.official_trains:
        st.warning(
            "조건에 맞는 열차가 없습니다. KTX 계열만 표시를 해제하거나 "
            "시간과 날짜를 변경해보세요."
        )
    else:
        result_df = pd.DataFrame(st.session_state.official_trains)

        edited_df = st.data_editor(
            result_df,
            hide_index=True,
            use_container_width=True,
            disabled=[
                "열차종류",
                "열차번호",
                "출발역",
                "도착역",
                "출발일시",
                "도착일시",
                "일반운임",
                "좌석상태",
            ],
            column_config={
                "선택": st.column_config.CheckboxColumn(
                    "선택",
                    help="연습용 모니터링에 사용할 열차 한 개를 선택하세요.",
                )
            },
            key="official_train_table",
        )

        selected_rows = edited_df[edited_df["선택"] == True]

        if st.session_state.monitor_active:
            st.warning("모니터링 중에는 열차를 변경하지 마세요.")
        elif selected_rows.empty:
            st.session_state.selected_train = None
            st.warning("열차 한 개를 선택하세요.")
        elif len(selected_rows) > 1:
            st.session_state.selected_train = None
            st.warning("열차 한 개만 선택할 수 있습니다.")
        else:
            selected_train = selected_rows.iloc[0].to_dict()
            st.session_state.selected_train = selected_train
            st.success(
                f"선택 완료: {selected_train['열차종류']} "
                f"{selected_train['열차번호']} · "
                f"{selected_train['출발일시']}"
            )


# =========================================================
# 11. 연습용 좌석 모니터링
# =========================================================
if st.session_state.selected_train:
    st.divider()
    st.subheader("④ 빈자리 알림 흐름 테스트")

    st.warning(
        "여기서 반복 확인하는 좌석 상태는 아직 가짜 데이터입니다. "
        "선택한 열차번호와 운행시간만 공식 데이터입니다."
    )

    col1, col2 = st.columns(2)

    with col1:
        monitor_interval = st.selectbox(
            "조회 간격",
            [5, 10, 15, 30],
            index=0,
            format_func=lambda value: f"{value}초",
            disabled=st.session_state.monitor_active,
        )

    with col2:
        available_after = st.selectbox(
            "연습용 빈자리 발견 시점",
            [2, 3, 5, 10],
            index=1,
            format_func=lambda value: f"{value}번째 조회",
            disabled=st.session_state.monitor_active,
        )

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "모니터링 시작",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.monitor_active,
        ):
            start_monitoring(monitor_interval, available_after)
            st.rerun()

    with col2:
        if st.button(
            "중지",
            use_container_width=True,
            disabled=not st.session_state.monitor_active,
        ):
            stop_monitoring()
            st.rerun()

    with col3:
        if st.button(
            "결과 초기화",
            use_container_width=True,
            disabled=st.session_state.monitor_active,
        ):
            reset_monitoring()
            st.rerun()


# =========================================================
# 12. 자동 반복 패널
# =========================================================
@st.fragment(run_every="1s")
def monitoring_panel() -> None:
    if (
        st.session_state.monitor_train is None
        and st.session_state.monitor_status == "대기"
    ):
        return

    st.divider()
    st.subheader("⑤ 모니터링 현황")

    now = datetime.now()
    next_check_at = st.session_state.monitor_next_check_at

    if (
        st.session_state.monitor_active
        and next_check_at is not None
        and now >= next_check_at
    ):
        check_count = st.session_state.monitor_check_count + 1
        st.session_state.monitor_check_count = check_count

        if check_count >= st.session_state.monitor_available_after:
            append_monitor_log(
                check_count,
                "빈자리 발견",
                "연습용 발견 조건 충족",
            )

            if not st.session_state.monitor_alert_sent:
                try:
                    send_message(
                        TELEGRAM_BOT_TOKEN,
                        st.session_state.telegram_chat_id,
                        build_alert_message(
                            st.session_state.monitor_train,
                            check_count,
                        ),
                    )
                except TelegramError as exc:
                    st.session_state.monitor_status = (
                        "빈자리 발견 · 알림 실패"
                    )
                    st.session_state.monitor_last_error = str(exc)
                    append_monitor_log(
                        check_count,
                        "알림 실패",
                        str(exc),
                    )
                else:
                    st.session_state.monitor_alert_sent = True
                    st.session_state.monitor_status = (
                        "빈자리 발견 · 알림 완료"
                    )
                    append_monitor_log(
                        check_count,
                        "알림 성공",
                        "이 사용자의 텔레그램으로 알림 전송",
                    )

            st.session_state.monitor_active = False
            st.session_state.monitor_next_check_at = None
        else:
            append_monitor_log(
                check_count,
                "매진",
                (
                    "연습용 좌석 확인 결과 매진 "
                    f"({st.session_state.monitor_available_after}번째 조회에서 발견 예정)"
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

    elapsed_seconds = 0
    if st.session_state.monitor_started_at is not None:
        elapsed_seconds = max(
            0,
            int(
                (
                    datetime.now()
                    - st.session_state.monitor_started_at
                ).total_seconds()
            ),
        )

    countdown = "-"
    if (
        st.session_state.monitor_active
        and st.session_state.monitor_next_check_at is not None
    ):
        countdown_seconds = max(
            0,
            int(
                (
                    st.session_state.monitor_next_check_at
                    - datetime.now()
                ).total_seconds()
            )
            + 1,
        )
        countdown = f"{countdown_seconds}초"

    col1, col2, col3 = st.columns(3)
    col1.metric("상태", status)
    col2.metric("조회 횟수", f"{check_count}회")
    col3.metric("다음 조회", countdown)

    st.caption(f"경과시간: {elapsed_seconds}초")

    if status == "빈자리 발견 · 알림 완료":
        st.success(
            "연습용 빈자리를 발견했고, 현재 사용자가 연결한 "
            "텔레그램으로 알림을 보냈습니다."
        )
    elif status == "빈자리 발견 · 알림 실패":
        st.error(st.session_state.monitor_last_error)
    elif st.session_state.monitor_active:
        st.info(
            "모니터링 중입니다. 현재 단계에서는 브라우저를 열어둬야 합니다."
        )

    if st.session_state.monitor_logs:
        st.dataframe(
            pd.DataFrame(st.session_state.monitor_logs),
            hide_index=True,
            use_container_width=True,
        )


monitoring_panel()


# =========================================================
# 13. 공개 서비스 전 남은 작업
# =========================================================
st.divider()

with st.expander("공개 서비스 출시 전 남은 필수 개발"):
    st.write(
        "1. Google 또는 이메일 로그인\n"
        "2. Supabase에 사용자와 Telegram 연결정보 저장\n"
        "3. 사용자별 모니터링 작업 DB 저장\n"
        "4. 브라우저를 닫아도 실행되는 백그라운드 Worker\n"
        "5. Telegram getUpdates를 Webhook 방식으로 교체\n"
        "6. 호출 횟수 제한, 이용약관, 개인정보처리방침\n"
        "7. 실제 좌석정보를 합법적으로 얻을 수 있는 방식 검증"
    )

st.caption(
    "현재 버전은 공개 베타 준비 단계입니다. 공식 열차 시간표를 사용하지만 "
    "실제 좌석 재고 조회와 자동 예매는 포함하지 않습니다."
)
