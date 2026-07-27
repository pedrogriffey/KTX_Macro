from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import requests
import streamlit as st


st.set_page_config(
    page_title="KTX 빈자리 모니터",
    page_icon="🚄",
    layout="centered",
)


STATION_NAMES = sorted(
    {
        # 수도권·경부선
        "서울", "용산", "영등포", "신도림", "안양", "수원", "오산",
        "서정리", "평택", "성환", "천안", "아산", "천안아산", "광명",
        "청량리", "왕십리", "상봉", "덕소", "양평", "용문", "지평",
        "가평", "강촌", "남춘천", "춘천",

        # 경부선·경부고속선
        "조치원", "오송", "대전", "서대전", "신탄진", "옥천", "이원",
        "영동", "황간", "추풍령", "김천", "김천구미", "구미", "왜관",
        "대구", "서대구", "동대구", "경산", "청도", "상동", "밀양",
        "삼랑진", "물금", "화명", "구포", "사상", "부산",

        # 강릉선·동해 방면
        "서원주", "만종", "횡성", "둔내", "평창", "진부(오대산)",
        "강릉", "정동진", "묵호", "동해",

        # 중앙선
        "석불", "일신", "매곡", "양동", "삼산", "원주", "봉양",
        "제천", "단양", "풍기", "영주", "안동", "의성", "탑리",
        "화본", "신녕", "영천",

        # 태백선·영동선
        "쌍룡", "영월", "예미", "민둥산", "사북", "고한", "태백",
        "동백산", "도계", "신기", "철암", "춘양", "봉화", "분천",
        "양원", "승부", "석포",

        # 충북선
        "청주", "오근장", "청주공항", "증평", "음성", "주덕", "충주", "삼탄",

        # 호남선
        "계룡", "논산", "강경", "함열", "익산", "김제", "신태인",
        "정읍", "백양사", "장성", "광주송정", "나주", "함평", "무안",
        "몽탄", "일로", "임성리", "목포", "공주",

        # 전라선
        "전주", "삼례", "임실", "오수", "남원", "곡성", "구례구",
        "순천", "여천", "여수엑스포",

        # 장항선
        "온양온천", "도고온천", "신례원", "예산", "삽교", "홍성",
        "광천", "청소", "대천", "웅천", "판교", "서천", "장항",
        "군산", "대야",

        # 경전선
        "진영", "창원중앙", "창원", "마산", "중리", "함안", "군북",
        "반성", "진주", "완사", "북천", "횡천", "하동", "진상",
        "광양", "벌교", "조성", "예당", "득량", "보성", "명봉",
        "이양", "능주", "화순", "효천", "서광주", "광주",

        # 동해선
        "부전", "센텀", "신해운대", "기장", "좌천", "남창", "태화강",
        "북울산", "경주", "서경주", "안강", "포항", "월포", "장사",
        "강구", "영덕",

        # 경북선·대구선
        "점촌", "용궁", "개포", "예천", "옥산", "청리", "상주", "함창",
        "하양", "아화", "건천",

        # 경의·경원·기타
        "문산", "임진강", "도라산", "연천", "전곡", "청산", "소요산",
        "동두천", "의정부", "대곡", "행신",
    }
)


def get_secret(name: str, default: str = "") -> str:
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
                "일반실": "매진" if index in (1, 2, 4) else "예약 가능",
                "특실": "매진" if index in (1, 3) else "예약 가능",
            }
        )

    return trains


def send_telegram_message(
    bot_token: str,
    chat_id: str,
    message: str,
) -> tuple[bool, str]:
    if not bot_token:
        return False, "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."

    if not chat_id:
        return False, "TELEGRAM_CHAT_ID가 설정되지 않았습니다."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        data = response.json()
    except requests.RequestException as exc:
        return False, f"텔레그램 서버 연결 오류: {exc}"
    except ValueError:
        return False, "텔레그램 서버 응답을 해석하지 못했습니다."

    if response.ok and data.get("ok") is True:
        return True, "텔레그램 메시지를 전송했습니다."

    return False, f"전송 실패: {data.get('description', '알 수 없는 오류')}"


def get_recent_telegram_chats(
    bot_token: str,
) -> tuple[bool, list[dict[str, str]] | str]:
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
        return False, f"텔레그램 서버 연결 오류: {exc}"
    except ValueError:
        return False, "텔레그램 서버 응답을 해석하지 못했습니다."

    if not response.ok or data.get("ok") is not True:
        return False, f"Chat ID 조회 실패: {data.get('description', '알 수 없는 오류')}"

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
                for part in [chat.get("first_name", ""), chat.get("last_name", "")]
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
            "최근 대화가 없습니다. 텔레그램에서 만든 봇을 열고 "
            "'시작' 또는 /start를 보낸 뒤 다시 조회하세요.",
        )

    return True, list(chats.values())


def build_test_message(selected_train: pd.Series) -> str:
    return (
        "🚄 KTX 빈자리 모니터 테스트\n\n"
        f"구간: {selected_train['출발역']} → {selected_train['도착역']}\n"
        f"열차: {selected_train['열차']} {selected_train['열차번호']}\n"
        f"시간: {selected_train['출발시각']} → {selected_train['도착시각']}\n\n"
        "텔레그램 연결이 정상적으로 작동합니다.\n"
        "현재 좌석 상태는 연습용 가짜 데이터입니다."
    )


st.title("🚄 KTX 빈자리 모니터")
st.caption("2단계 연습용 앱 · 전국 역 검색 및 텔레그램 테스트")

st.info(
    "역 이름을 입력하면 목록이 검색됩니다. "
    "목록에 없는 역도 이름을 직접 입력해 선택할 수 있습니다. "
    "현재 열차와 좌석 상태는 연습용 가짜 데이터입니다."
)


with st.form("search_form"):
    st.subheader("조회 조건")

    col1, col2 = st.columns(2)

    with col1:
        departure_station = st.selectbox(
            "출발역",
            options=STATION_NAMES,
            index=STATION_NAMES.index("서울"),
            placeholder="역 이름 검색 또는 직접 입력",
            accept_new_options=True,
            filter_mode="contains",
            help="목록을 열고 역 이름을 입력하세요. 없는 역도 직접 추가할 수 있습니다.",
        )

    with col2:
        arrival_station = st.selectbox(
            "도착역",
            options=STATION_NAMES,
            index=STATION_NAMES.index("부산"),
            placeholder="역 이름 검색 또는 직접 입력",
            accept_new_options=True,
            filter_mode="contains",
            help="목록을 열고 역 이름을 입력하세요. 없는 역도 직접 추가할 수 있습니다.",
        )

    travel_date = st.date_input(
        "출발 날짜",
        value=date.today() + timedelta(days=1),
        min_value=date.today(),
    )

    after_hour = st.selectbox(
        "이 시간 이후 열차",
        options=list(range(0, 24)),
        index=9,
        format_func=lambda hour: f"{hour:02d}:00 이후",
    )

    submitted = st.form_submit_button(
        "연습용 열차 조회",
        type="primary",
        use_container_width=True,
    )


if submitted:
    departure_station = str(departure_station).strip()
    arrival_station = str(arrival_station).strip()

    if not departure_station or not arrival_station:
        st.error("출발역과 도착역을 모두 입력하세요.")
    elif departure_station == arrival_station:
        st.error("출발역과 도착역은 서로 달라야 합니다.")
    else:
        st.session_state["search_result"] = make_mock_trains(
            departure_station=departure_station,
            arrival_station=arrival_station,
            travel_date=travel_date,
            after_hour=after_hour,
        )
        st.session_state["search_summary"] = {
            "departure_station": departure_station,
            "arrival_station": arrival_station,
            "travel_date": travel_date.strftime("%Y-%m-%d"),
            "after_hour": after_hour,
        }


if "search_result" in st.session_state:
    summary = st.session_state["search_summary"]

    st.divider()
    st.subheader("조회 결과")

    st.write(
        f"**{summary['departure_station']} → {summary['arrival_station']}** · "
        f"{summary['travel_date']} · {summary['after_hour']:02d}:00 이후"
    )

    result_df = pd.DataFrame(st.session_state["search_result"])

    edited_df = st.data_editor(
        result_df,
        hide_index=True,
        use_container_width=True,
        disabled=[
            "열차", "열차번호", "출발역", "도착역", "출발시각", "도착시각", "일반실", "특실",
        ],
        column_config={
            "선택": st.column_config.CheckboxColumn(
                "선택",
                help="텔레그램 테스트에 사용할 열차 한 개를 선택하세요.",
            )
        },
        key="train_table",
    )

    selected_trains = edited_df[edited_df["선택"] == True]

    if selected_trains.empty:
        st.warning("텔레그램 테스트에 사용할 열차를 한 개 선택하세요.")
        st.session_state.pop("selected_train", None)
    elif len(selected_trains) > 1:
        st.warning("이번 단계에서는 열차 한 개만 선택하세요.")
        st.session_state.pop("selected_train", None)
    else:
        selected_train = selected_trains.iloc[0]
        st.session_state["selected_train"] = selected_train.to_dict()
        st.success(f"선택한 열차번호: {selected_train['열차번호']}")


st.divider()
st.subheader("텔레그램 알림 테스트")

bot_token = get_secret("TELEGRAM_BOT_TOKEN")
chat_id = get_secret("TELEGRAM_CHAT_ID")
setup_pin = get_secret("SETUP_PIN")

if not bot_token:
    st.warning("Streamlit Secrets에 TELEGRAM_BOT_TOKEN을 먼저 등록해야 합니다.")
else:
    st.success("텔레그램 봇 토큰이 서버에 등록되어 있습니다.")

if chat_id:
    st.success("텔레그램 Chat ID가 서버에 등록되어 있습니다.")
else:
    st.warning("TELEGRAM_CHAT_ID가 아직 등록되지 않았습니다.")

with st.expander("처음 연결할 때: Chat ID 찾기"):
    st.write(
        "공개 앱에서 다른 사람이 Chat ID를 조회하지 못하도록 "
        "SETUP_PIN으로 보호합니다."
    )

    entered_pin = st.text_input(
        "관리자 설정 PIN",
        type="password",
        key="entered_setup_pin",
    )

    if st.button("최근 Chat ID 찾기", use_container_width=True):
        if not setup_pin:
            st.error("Streamlit Secrets에 SETUP_PIN이 설정되지 않았습니다.")
        elif entered_pin != setup_pin:
            st.error("관리자 설정 PIN이 일치하지 않습니다.")
        else:
            success, result = get_recent_telegram_chats(bot_token)

            if success:
                st.success(
                    "Chat ID를 찾았습니다. 아래 값을 복사해 "
                    "Streamlit Secrets의 TELEGRAM_CHAT_ID에 등록하세요."
                )
                st.dataframe(
                    pd.DataFrame(result),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.error(str(result))


selected_train_dict = st.session_state.get("selected_train")

if st.button(
    "선택한 열차로 텔레그램 테스트 알림 보내기",
    type="primary",
    use_container_width=True,
    disabled=not (bot_token and chat_id and selected_train_dict),
):
    selected_train_series = pd.Series(selected_train_dict)
    test_message = build_test_message(selected_train_series)

    success, message = send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        message=test_message,
    )

    if success:
        st.success(message)
        st.balloons()
    else:
        st.error(message)


st.divider()
st.caption(
    "현재 버전은 학습용입니다. 실제 코레일 로그인, 실제 좌석 조회, "
    "자동 반복 모니터링 및 자동 예매 기능은 포함되어 있지 않습니다."
)
