from __future__ import annotations

from datetime import date, datetime, timedelta
import secrets
import time
from typing import Any

import pandas as pd
import streamlit as st

from supabase_auth import (
    SupabaseAuthError,
    clear_telegram_profile,
    ensure_profile,
    restore_authenticated_client,
    save_telegram_profile,
    sign_in_with_password,
    sign_out,
    sign_up_with_password,
)
from monitor_jobs_service import (
    MonitorJobError,
    activate_monitor_job_test,
    create_monitor_job,
    delete_monitor_job,
    format_job_datetime,
    get_worker_health,
    list_monitor_jobs,
    pause_monitor_job,
    reset_monitor_job,
)
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
# 2. Session State
# =========================================================
def initialize_state() -> None:
    defaults: dict[str, Any] = {
        "telegram_link_code": secrets.token_urlsafe(12).replace("-", "_"),
        "telegram_chat_id": "",
        "telegram_display_name": "",
        "profile_loaded_user_id": "",
        "official_trains": None,
        "search_summary": None,
        "selected_train": None,
        "monitor_active": False,
        "monitor_status": "대기",
        "monitor_check_count": 0,
        "monitor_started_at": None,
        "monitor_next_check_at": None,
        "monitor_interval": 3,
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


def clear_user_runtime_state() -> None:
    for key in (
        "telegram_chat_id",
        "telegram_display_name",
        "profile_loaded_user_id",
        "official_trains",
        "search_summary",
        "selected_train",
        "monitor_active",
        "monitor_status",
        "monitor_check_count",
        "monitor_started_at",
        "monitor_next_check_at",
        "monitor_logs",
        "monitor_alert_sent",
        "monitor_last_error",
        "monitor_train",
    ):
        st.session_state.pop(key, None)

    st.session_state.telegram_link_code = (
        secrets.token_urlsafe(12).replace("-", "_")
    )
    initialize_state()


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
SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = get_secret(
    "SUPABASE_PUBLISHABLE_KEY"
)

missing_secrets = [
    name
    for name, value in (
        ("DATA_GO_KR_SERVICE_KEY", DATA_GO_KR_SERVICE_KEY),
        ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
        ("SUPABASE_URL", SUPABASE_URL),
        (
            "SUPABASE_PUBLISHABLE_KEY",
            SUPABASE_PUBLISHABLE_KEY,
        ),
    )
    if not value
]

if missing_secrets:
    st.error(
        "Streamlit Secrets에 다음 값이 필요합니다: "
        + ", ".join(missing_secrets)
    )
    st.code(
        'DATA_GO_KR_SERVICE_KEY = "공공데이터 인증키"\n'
        'TELEGRAM_BOT_TOKEN = "Telegram Bot Token"\n'
        'SUPABASE_URL = "https://프로젝트ID.supabase.co"\n'
        'SUPABASE_PUBLISHABLE_KEY = "sb_publishable_..."',
        language="toml",
    )
    st.stop()


# =========================================================
# 4. 캐시
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
# 5. 인증 세션 복원
# =========================================================
try:
    supabase_client, auth_user = restore_authenticated_client(
        SUPABASE_URL,
        SUPABASE_PUBLISHABLE_KEY,
        st.session_state,
    )
except SupabaseAuthError as exc:
    st.error(str(exc))
    st.stop()


# =========================================================
# 6. 로그인 화면
# =========================================================
st.title("🚄 KTX 빈자리 모니터")
st.caption("7A 단계 · 백그라운드 Worker 실행 테스트")

if auth_user is None:
    st.info(
        "계정을 만들거나 로그인해야 열차 조회와 알림 기능을 사용할 수 있습니다."
    )

    login_tab, signup_tab = st.tabs(
        ["로그인", "회원가입"]
    )

    with login_tab:
        with st.form("login_form"):
            login_email = st.text_input(
                "이메일",
                placeholder="name@example.com",
            )
            login_password = st.text_input(
                "비밀번호",
                type="password",
            )
            login_submitted = st.form_submit_button(
                "로그인",
                type="primary",
                use_container_width=True,
            )

        if login_submitted:
            if not login_email.strip() or not login_password:
                st.error("이메일과 비밀번호를 모두 입력하세요.")
            else:
                try:
                    client, user = sign_in_with_password(
                        SUPABASE_URL,
                        SUPABASE_PUBLISHABLE_KEY,
                        st.session_state,
                        login_email,
                        login_password,
                    )
                    ensure_profile(
                        client,
                        user["id"],
                        user["email"],
                    )
                except SupabaseAuthError as exc:
                    st.error(str(exc))
                else:
                    st.success("로그인했습니다.")
                    st.rerun()

    with signup_tab:
        with st.form("signup_form"):
            signup_email = st.text_input(
                "가입 이메일",
                placeholder="name@example.com",
            )
            signup_password = st.text_input(
                "가입 비밀번호",
                type="password",
                help="8자 이상을 권장합니다.",
            )
            signup_password_confirm = st.text_input(
                "비밀번호 확인",
                type="password",
            )
            signup_submitted = st.form_submit_button(
                "회원가입",
                type="primary",
                use_container_width=True,
            )

        if signup_submitted:
            email = signup_email.strip()
            password = signup_password

            if not email or not password:
                st.error("이메일과 비밀번호를 모두 입력하세요.")
            elif len(password) < 8:
                st.error("비밀번호는 8자 이상으로 입력하세요.")
            elif password != signup_password_confirm:
                st.error("비밀번호 확인이 일치하지 않습니다.")
            else:
                try:
                    client, user, confirmation_required = (
                        sign_up_with_password(
                            SUPABASE_URL,
                            SUPABASE_PUBLISHABLE_KEY,
                            st.session_state,
                            email,
                            password,
                        )
                    )

                    if not confirmation_required and user:
                        ensure_profile(
                            client,
                            user["id"],
                            user["email"],
                        )
                except SupabaseAuthError as exc:
                    st.error(str(exc))
                else:
                    if confirmation_required:
                        st.success(
                            "회원가입 요청이 완료됐습니다. "
                            "이메일 인증 후 로그인하세요."
                        )
                    else:
                        st.success(
                            "회원가입과 로그인이 완료됐습니다."
                        )
                        st.rerun()

    st.caption(
        "비밀번호는 앱이 직접 저장하지 않으며 Supabase Auth가 처리합니다."
    )
    st.stop()


# =========================================================
# 7. 로그인 사용자 프로필
# =========================================================
user_id = auth_user["id"]
user_email = auth_user["email"]

try:
    profile = ensure_profile(
        supabase_client,
        user_id,
        user_email,
    )
except SupabaseAuthError as exc:
    st.error(str(exc))
    st.stop()

if st.session_state.profile_loaded_user_id != user_id:
    st.session_state.telegram_chat_id = str(
        profile.get("telegram_chat_id") or ""
    )
    st.session_state.telegram_display_name = str(
        profile.get("telegram_display_name") or ""
    )
    st.session_state.profile_loaded_user_id = user_id
    st.session_state.telegram_link_code = (
        secrets.token_urlsafe(12).replace("-", "_")
    )

account_col, logout_col = st.columns([3, 1])

with account_col:
    st.success(f"로그인 계정: {user_email}")

with logout_col:
    if st.button(
        "로그아웃",
        use_container_width=True,
    ):
        sign_out(
            supabase_client,
            st.session_state,
        )
        clear_user_runtime_state()
        st.rerun()

st.info(
    "Telegram 연결정보는 현재 로그인한 사용자 프로필에 저장됩니다. "
    "다음에 다시 로그인하면 자동으로 복원됩니다."
)


# =========================================================
# 8. Telegram 연결
# =========================================================
st.subheader("① 내 텔레그램 연결")

try:
    bot_profile = load_bot_profile(TELEGRAM_BOT_TOKEN)
    bot_username = str(
        bot_profile.get("username", "")
    ).strip()
except TelegramError as exc:
    st.error(str(exc))
    st.stop()

if not bot_username:
    st.error("텔레그램 봇 사용자명을 확인하지 못했습니다.")
    st.stop()

if st.session_state.telegram_chat_id:
    st.success(
        "연결 완료: "
        f"{st.session_state.telegram_display_name or 'Telegram 사용자'}"
    )

    telegram_test_col, telegram_clear_col = st.columns(2)

    with telegram_test_col:
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
                        f"로그인 계정: {user_email}\n"
                        "알림 연결정보가 사용자 계정에 저장돼 있습니다."
                    ),
                )
                st.success("테스트 메시지를 보냈습니다.")
            except TelegramError as exc:
                st.error(str(exc))

    with telegram_clear_col:
        if st.button(
            "텔레그램 연결 해제",
            use_container_width=True,
        ):
            try:
                clear_telegram_profile(
                    supabase_client,
                    user_id,
                )
            except SupabaseAuthError as exc:
                st.error(str(exc))
            else:
                st.session_state.telegram_chat_id = ""
                st.session_state.telegram_display_name = ""
                st.session_state.telegram_link_code = (
                    secrets.token_urlsafe(12).replace("-", "_")
                )
                st.success("텔레그램 연결을 해제했습니다.")
                st.rerun()
else:
    link_code = st.session_state.telegram_link_code
    bot_link = (
        f"https://t.me/{bot_username}"
        f"?start={link_code}"
    )

    st.write(
        "아래 버튼을 누르고 Telegram에서 **시작**을 누른 뒤, "
        "앱으로 돌아와 연결 확인을 누르세요."
    )

    st.link_button(
        "텔레그램에서 내 알림 연결하기",
        bot_link,
        use_container_width=True,
        type="primary",
    )

    st.caption(
        f"현재 로그인 세션의 일회용 연결코드: `{link_code}`"
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
                    "연결 메시지를 아직 찾지 못했습니다. "
                    "Telegram에서 시작을 누른 뒤 다시 확인하세요."
                )
            else:
                try:
                    save_telegram_profile(
                        supabase_client,
                        user_id=user_id,
                        email=user_email,
                        chat_id=matched_chat["chat_id"],
                        display_name=matched_chat["display_name"],
                    )
                except SupabaseAuthError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.telegram_chat_id = (
                        matched_chat["chat_id"]
                    )
                    st.session_state.telegram_display_name = (
                        matched_chat["display_name"]
                    )
                    st.success(
                        "텔레그램 연결정보를 사용자 계정에 저장했습니다."
                    )
                    st.rerun()



# =========================================================
# 9. 내 저장 작업 및 Worker 제어
# =========================================================
st.divider()
st.subheader("② 내 저장 작업")

try:
    worker_health = get_worker_health(
        supabase_client
    )
except MonitorJobError as exc:
    st.warning(str(exc))
    worker_health = {
        "is_online": False,
        "last_seen_at": None,
        "worker_version": None,
        "seconds_since_heartbeat": None,
    }

if worker_health.get("is_online") is True:
    st.success(
        "백그라운드 Worker 연결 정상"
        f" · 버전 {worker_health.get('worker_version') or '-'}"
        f" · 최근 신호 "
        f"{worker_health.get('seconds_since_heartbeat') or 0}초 전"
    )
else:
    st.warning(
        "백그라운드 Worker가 아직 연결되지 않았거나 "
        "최근 45초 동안 신호가 없습니다."
    )

try:
    saved_jobs = list_monitor_jobs(
        supabase_client,
        user_id,
    )
except MonitorJobError as exc:
    st.error(str(exc))
    saved_jobs = []

STATUS_LABELS = {
    "draft": "준비",
    "active": "백그라운드 실행 중",
    "paused": "일시정지",
    "completed": "완료",
    "error": "오류",
}

SEAT_CLASS_LABELS = {
    "general": "일반실",
    "special": "특실",
    "any": "일반실 또는 특실",
}

RESULT_LABELS = {
    "simulation_sold_out": "연습용 매진",
    "simulation_available": "연습용 빈자리 발견",
    "train_departed": "열차 출발시간 경과",
}

if not saved_jobs:
    st.info(
        "저장된 작업이 없습니다. 아래에서 공식 열차를 조회하고 "
        "모니터링 작업을 저장하세요."
    )
else:
    saved_job_rows = []

    for job in saved_jobs:
        saved_job_rows.append(
            {
                "상태": STATUS_LABELS.get(
                    str(job.get("status", "")),
                    str(job.get("status", "")),
                ),
                "구간": (
                    f"{job.get('departure_station_name', '')}"
                    f" → {job.get('arrival_station_name', '')}"
                ),
                "열차": (
                    f"{job.get('train_type', '')} "
                    f"{job.get('train_no', '')}"
                ).strip(),
                "출발": format_job_datetime(
                    job.get("departure_planned_at")
                ),
                "좌석": SEAT_CLASS_LABELS.get(
                    str(job.get("seat_class", "")),
                    str(job.get("seat_class", "")),
                ),
                "간격": (
                    f"{job.get('check_interval_seconds', '-')}초"
                ),
                "조회": (
                    f"{job.get('worker_check_count', 0)}회"
                ),
                "최근 결과": RESULT_LABELS.get(
                    str(job.get("last_result", "")),
                    str(job.get("last_result") or "-"),
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(saved_job_rows),
        hide_index=True,
        use_container_width=True,
    )

    job_option_ids = [
        str(job["id"])
        for job in saved_jobs
    ]
    job_by_id = {
        str(job["id"]): job
        for job in saved_jobs
    }

    selected_saved_job_id = st.selectbox(
        "관리할 작업 선택",
        job_option_ids,
        format_func=lambda job_id: (
            f"{job_by_id[job_id].get('departure_station_name', '')}"
            f" → "
            f"{job_by_id[job_id].get('arrival_station_name', '')}"
            f" · "
            f"{job_by_id[job_id].get('train_type', '')} "
            f"{job_by_id[job_id].get('train_no', '')}"
            f" · "
            f"{format_job_datetime(job_by_id[job_id].get('departure_planned_at'))}"
        ),
        key="saved_job_selector_step7a",
    )

    selected_saved_job = job_by_id[
        selected_saved_job_id
    ]
    selected_saved_status = str(
        selected_saved_job.get("status", "draft")
    )

    if selected_saved_job.get("last_error"):
        st.error(
            "최근 Worker 오류: "
            f"{selected_saved_job.get('last_error')}"
        )

    simulation_available_after = st.selectbox(
        "백그라운드 테스트 빈자리 발견 시점",
        options=[2, 3, 5, 10],
        index=1,
        format_func=lambda count: f"{count}번째 조회",
        disabled=(
            selected_saved_status == "active"
        ),
        help=(
            "실제 좌석정보가 아니라 Worker와 Telegram이 "
            "정상 동작하는지 확인하기 위한 테스트 조건입니다."
        ),
    )

    action_col1, action_col2, action_col3 = st.columns(3)

    with action_col1:
        if selected_saved_status == "active":
            if st.button(
                "백그라운드 일시정지",
                use_container_width=True,
            ):
                try:
                    pause_monitor_job(
                        supabase_client,
                        job_id=selected_saved_job_id,
                    )
                except MonitorJobError as exc:
                    st.error(str(exc))
                else:
                    st.success("작업을 일시정지했습니다.")
                    st.rerun()
        else:
            if st.button(
                "백그라운드 테스트 시작",
                type="primary",
                use_container_width=True,
                disabled=(
                    not st.session_state.telegram_chat_id
                    or worker_health.get("is_online") is not True
                ),
            ):
                try:
                    activate_monitor_job_test(
                        supabase_client,
                        job_id=selected_saved_job_id,
                        available_after_checks=(
                            simulation_available_after
                        ),
                    )
                except MonitorJobError as exc:
                    st.error(str(exc))
                else:
                    st.success(
                        "백그라운드 테스트를 시작했습니다. "
                        "이제 브라우저를 닫아도 Worker가 계속 실행합니다."
                    )
                    st.rerun()

    with action_col2:
        if st.button(
            "준비 상태로 초기화",
            use_container_width=True,
            disabled=(
                selected_saved_status == "active"
            ),
        ):
            try:
                reset_monitor_job(
                    supabase_client,
                    job_id=selected_saved_job_id,
                )
            except MonitorJobError as exc:
                st.error(str(exc))
            else:
                st.success(
                    "작업을 준비 상태로 초기화했습니다."
                )
                st.rerun()

    with action_col3:
        delete_confirmed = st.checkbox(
            "삭제 확인",
            key=f"delete_confirm_{selected_saved_job_id}",
        )

        if st.button(
            "선택 작업 삭제",
            use_container_width=True,
            disabled=(
                not delete_confirmed
                or selected_saved_status == "active"
            ),
        ):
            try:
                delete_monitor_job(
                    supabase_client,
                    user_id=user_id,
                    job_id=selected_saved_job_id,
                )
            except MonitorJobError as exc:
                st.error(str(exc))
            else:
                st.success("저장 작업을 삭제했습니다.")
                st.rerun()

    st.caption(
        "현재 Worker는 실제 코레일 좌석이 아니라 연습용 상태를 조회합니다. "
        "조회 간격은 저장한 3초 이상의 값을 그대로 사용합니다."
    )


# =========================================================
# 10. 모니터링 함수
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
        st.error("모니터링할 열차를 한 개 선택하세요.")
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
        "빈자리 발견은 아직 연습용 시뮬레이션입니다."
    )


# =========================================================
# 11. 공식 역 목록
# =========================================================
st.divider()
st.subheader("③ 공식 열차 조회")

try:
    with st.spinner("공식 역 목록을 불러오는 중입니다..."):
        stations = load_official_stations(
            DATA_GO_KR_SERVICE_KEY
        )
except TagoAPIError as exc:
    st.error(str(exc))
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
    station_col1, station_col2 = st.columns(2)

    with station_col1:
        departure_station_id = st.selectbox(
            "출발역",
            station_ids,
            index=find_station_default("청량리"),
            format_func=station_label,
        )

    with station_col2:
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
        elapsed = (
            time.monotonic()
            - st.session_state.last_search_monotonic
        )

        if elapsed < 3:
            st.warning("잠시 후 다시 조회하세요.")
        else:
            st.session_state.last_search_monotonic = (
                time.monotonic()
            )
            reset_monitoring()

            departure_station = station_map[
                departure_station_id
            ]
            arrival_station = station_map[
                arrival_station_id
            ]

            try:
                with st.spinner(
                    "공식 열차 시간표를 조회하는 중입니다..."
                ):
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
                    "departure_station_id": (
                        departure_station_id
                    ),
                    "departure_station": (
                        departure_station["station_name"]
                    ),
                    "arrival_station_id": (
                        arrival_station_id
                    ),
                    "arrival_station": (
                        arrival_station["station_name"]
                    ),
                    "travel_date": travel_date.strftime(
                        "%Y-%m-%d"
                    ),
                    "after_hour": after_hour,
                    "ktx_only": ktx_only,
                }
                st.session_state.selected_train = None


# =========================================================
# 12. 열차 선택
# =========================================================
if st.session_state.official_trains is not None:
    summary = st.session_state.search_summary

    st.divider()
    st.subheader("④ 모니터링할 열차 선택")

    st.write(
        f"**{summary['departure_station']} → "
        f"{summary['arrival_station']}** · "
        f"{summary['travel_date']} · "
        f"{summary['after_hour']:02d}:00 이후"
    )

    if not st.session_state.official_trains:
        st.warning(
            "조건에 맞는 열차가 없습니다. "
            "KTX 계열만 표시를 해제하거나 조건을 변경하세요."
        )
    else:
        result_df = pd.DataFrame(
            st.session_state.official_trains
        )

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
                )
            },
            key="official_train_table_step5b",
        )

        selected_rows = edited_df[
            edited_df["선택"] == True
        ]

        if st.session_state.monitor_active:
            st.warning(
                "모니터링 중에는 열차를 변경하지 마세요."
            )
        elif selected_rows.empty:
            st.session_state.selected_train = None
            st.warning("열차 한 개를 선택하세요.")
        elif len(selected_rows) > 1:
            st.session_state.selected_train = None
            st.warning("열차 한 개만 선택할 수 있습니다.")
        else:
            selected_train = (
                selected_rows.iloc[0].to_dict()
            )
            st.session_state.selected_train = (
                selected_train
            )
            st.success(
                f"선택 완료: "
                f"{selected_train['열차종류']} "
                f"{selected_train['열차번호']} · "
                f"{selected_train['출발일시']}"
            )


# =========================================================
# 13. 작업 저장 및 브라우저 테스트
# =========================================================
if st.session_state.selected_train:
    st.divider()
    st.subheader("⑤ 모니터링 작업 저장")

    selected_train = st.session_state.selected_train
    summary = st.session_state.search_summary

    st.write(
        f"**{selected_train['열차종류']} "
        f"{selected_train['열차번호']}** · "
        f"{selected_train['출발일시']} 출발"
    )

    condition_col1, condition_col2 = st.columns(2)

    with condition_col1:
        seat_class = st.selectbox(
            "좌석 조건",
            options=["general", "special", "any"],
            format_func=lambda value: {
                "general": "일반실",
                "special": "특실",
                "any": "일반실 또는 특실",
            }[value],
        )

    with condition_col2:
        monitor_interval = st.selectbox(
            "조회 간격",
            options=[3, 5, 10, 15, 30, 60, 300],
            index=1,
            format_func=lambda value: (
                f"{value}초"
                if value < 60
                else (
                    "1분"
                    if value == 60
                    else f"{value // 60}분"
                )
            ),
            disabled=st.session_state.monitor_active,
            help=(
                "저장 가능한 최소 조회 간격은 3초입니다. "
                "실제 Worker 운영 시 서비스 부하와 외부 서비스 정책에 따라 "
                "더 긴 간격이 적용될 수 있습니다."
            ),
        )

    if not st.session_state.telegram_chat_id:
        st.warning(
            "알림을 받을 수 있도록 먼저 본인의 Telegram을 연결하세요."
        )

    if st.button(
        "이 조건으로 모니터링 작업 저장",
        type="primary",
        use_container_width=True,
        disabled=not st.session_state.telegram_chat_id,
    ):
        try:
            create_monitor_job(
                supabase_client,
                user_id=user_id,
                departure_station_id=summary[
                    "departure_station_id"
                ],
                departure_station_name=summary[
                    "departure_station"
                ],
                arrival_station_id=summary[
                    "arrival_station_id"
                ],
                arrival_station_name=summary[
                    "arrival_station"
                ],
                travel_date=summary["travel_date"],
                train_type=str(
                    selected_train["열차종류"]
                ),
                train_no=str(
                    selected_train["열차번호"]
                ),
                departure_planned_at=str(
                    selected_train["출발일시"]
                ),
                arrival_planned_at=str(
                    selected_train["도착일시"]
                ),
                seat_class=seat_class,
                check_interval_seconds=monitor_interval,
            )
        except MonitorJobError as exc:
            st.error(str(exc))
        else:
            st.success(
                "모니터링 작업을 저장했습니다. "
                "내 저장 작업 목록에서 확인할 수 있습니다."
            )
            st.rerun()

    st.caption(
        "저장된 작업은 아직 자동 실행되지 않습니다. "
        "백그라운드 Worker를 연결한 뒤 실제 실행 대상으로 전환합니다."
    )

    st.divider()
    st.subheader("⑥ 브라우저 알림 흐름 테스트")

    st.warning(
        "선택한 열차번호와 시간표는 공식 데이터지만, "
        "좌석 발견은 아직 연습용 시뮬레이션입니다."
    )

    available_after = st.selectbox(
        "연습용 빈자리 발견 시점",
        [2, 3, 5, 10],
        index=1,
        format_func=lambda value: f"{value}번째 조회",
        disabled=st.session_state.monitor_active,
    )

    start_col, stop_col, reset_col = st.columns(3)

    with start_col:
        if st.button(
            "브라우저 테스트 시작",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.monitor_active,
        ):
            start_monitoring(
                monitor_interval,
                available_after,
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
# 14. 자동 모니터링 패널
# =========================================================
@st.fragment(run_every="1s")
def monitoring_panel() -> None:
    if (
        st.session_state.monitor_train is None
        and st.session_state.monitor_status == "대기"
    ):
        return

    st.divider()
    st.subheader("⑦ 브라우저 테스트 현황")

    now = datetime.now()
    next_check_at = (
        st.session_state.monitor_next_check_at
    )

    if (
        st.session_state.monitor_active
        and next_check_at is not None
        and now >= next_check_at
    ):
        check_count = (
            st.session_state.monitor_check_count + 1
        )
        st.session_state.monitor_check_count = check_count

        if (
            check_count
            >= st.session_state.monitor_available_after
        ):
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
                    st.session_state.monitor_last_error = (
                        str(exc)
                    )
                    append_monitor_log(
                        check_count,
                        "알림 실패",
                        str(exc),
                    )
                else:
                    st.session_state.monitor_alert_sent = (
                        True
                    )
                    st.session_state.monitor_status = (
                        "빈자리 발견 · 알림 완료"
                    )
                    append_monitor_log(
                        check_count,
                        "알림 성공",
                        "현재 로그인 사용자의 Telegram으로 전송",
                    )

            st.session_state.monitor_active = False
            st.session_state.monitor_next_check_at = None
        else:
            append_monitor_log(
                check_count,
                "매진",
                (
                    "연습용 좌석 확인 결과 매진 "
                    f"({st.session_state.monitor_available_after}"
                    "번째 조회에서 발견 예정)"
                ),
            )
            st.session_state.monitor_next_check_at = (
                now
                + timedelta(
                    seconds=(
                        st.session_state.monitor_interval
                    )
                )
            )

    status = st.session_state.monitor_status
    check_count = (
        st.session_state.monitor_check_count
    )

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
        and st.session_state.monitor_next_check_at
        is not None
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

    status_col, count_col, next_col = st.columns(3)
    status_col.metric("상태", status)
    count_col.metric("조회 횟수", f"{check_count}회")
    next_col.metric("다음 조회", countdown)

    st.caption(f"경과시간: {elapsed_seconds}초")

    if status == "빈자리 발견 · 알림 완료":
        st.success(
            "현재 로그인 사용자의 Telegram으로 "
            "테스트 알림을 보냈습니다."
        )
    elif status == "빈자리 발견 · 알림 실패":
        st.error(st.session_state.monitor_last_error)
    elif st.session_state.monitor_active:
        st.info(
            "현재 단계에서는 브라우저를 열어둬야 합니다."
        )

    if st.session_state.monitor_logs:
        st.dataframe(
            pd.DataFrame(
                st.session_state.monitor_logs
            ),
            hide_index=True,
            use_container_width=True,
        )


monitoring_panel()


# =========================================================
# 15. 안내
# =========================================================
st.divider()

with st.expander("현재 공개 서비스 준비 상태"):
    st.write(
        "- 사용자 이메일 회원가입·로그인 적용\n"
        "- 사용자별 Telegram 연결정보 영구 저장\n"
        "- RLS로 다른 사용자의 프로필 접근 차단\n"
        "- 공식 열차 시간표 조회 적용\n"
        "- 사용자별 모니터링 작업 영구 저장\n"
        "- 저장 작업 일시정지·초기화·삭제\n"
        "- 최소 조회 간격 3초 적용\n"
        "- Render 백그라운드 Worker 연결\n"
        "- 브라우저 종료 후 Telegram 테스트 알림\n\n"
        "다음 단계에서는 연습용 공급자를 실제 좌석정보 공급자로 "
        "교체할 수 있는 합법적·안정적 방식을 검증합니다."
    )

st.caption(
    "현재 실제 잔여좌석 조회 및 자동예매 기능은 포함하지 않습니다."
)
