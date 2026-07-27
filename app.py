from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st


# ---------------------------------------------------------
# 1. 페이지 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="KTX 빈자리 모니터",
    page_icon="🚄",
    layout="centered",
)


# ---------------------------------------------------------
# 2. 연습용 가짜 열차 데이터 생성 함수
#    아직 코레일과 연결하지 않습니다.
# ---------------------------------------------------------
def make_mock_trains(
    departure_station: str,
    arrival_station: str,
    travel_date: date,
    after_hour: int,
) -> list[dict]:
    """사용자가 입력한 조건을 바탕으로 연습용 KTX 목록을 만듭니다."""

    base_time = datetime.combine(
        travel_date,
        datetime.min.time(),
    ).replace(hour=after_hour)

    # 출발 시각이 서로 다른 가짜 열차 4개를 생성합니다.
    trains = []
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


# ---------------------------------------------------------
# 3. 화면 상단
# ---------------------------------------------------------
st.title("🚄 KTX 빈자리 모니터")
st.caption("1단계 연습용 앱 · 아직 실제 코레일 좌석과 연결되지 않습니다.")

st.info(
    "이번 단계에서는 화면과 입력 기능만 만듭니다. "
    "표시되는 열차와 좌석 상태는 모두 연습용 가짜 데이터입니다."
)


# ---------------------------------------------------------
# 4. 조회 조건 입력 폼
# ---------------------------------------------------------
station_options = [
    "서울",
    "용산",
    "광명",
    "수원",
    "천안아산",
    "오송",
    "대전",
    "동대구",
    "울산",
    "부산",
    "익산",
    "전주",
    "광주송정",
    "목포",
    "강릉",
]

with st.form("search_form"):
    st.subheader("조회 조건")

    col1, col2 = st.columns(2)

    with col1:
        departure_station = st.selectbox(
            "출발역",
            station_options,
            index=0,
        )

    with col2:
        arrival_station = st.selectbox(
            "도착역",
            station_options,
            index=9,
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


# ---------------------------------------------------------
# 5. 입력값 확인 및 결과 표시
# ---------------------------------------------------------
if submitted:
    if departure_station == arrival_station:
        st.error("출발역과 도착역은 서로 달라야 합니다.")
    else:
        trains = make_mock_trains(
            departure_station=departure_station,
            arrival_station=arrival_station,
            travel_date=travel_date,
            after_hour=after_hour,
        )

        # Streamlit이 다시 실행되더라도 결과를 유지하기 위해 session_state에 저장합니다.
        st.session_state["search_result"] = trains
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
        f"{summary['travel_date']} · "
        f"{summary['after_hour']:02d}:00 이후"
    )

    result_df = pd.DataFrame(st.session_state["search_result"])

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
                help="나중에 모니터링할 열차를 선택하는 칸입니다.",
            )
        },
        key="train_table",
    )

    selected_trains = edited_df[edited_df["선택"] == True]

    if selected_trains.empty:
        st.warning("모니터링할 열차의 '선택' 체크박스를 선택하세요.")
    else:
        selected_numbers = ", ".join(selected_trains["열차번호"].astype(str))
        st.success(f"선택한 열차번호: {selected_numbers}")

        if st.button(
            "선택 내용 확인",
            use_container_width=True,
        ):
            st.success(
                "1단계 기능이 정상 작동했습니다. "
                "다음 단계에서 텔레그램 테스트 알림을 연결합니다."
            )


# ---------------------------------------------------------
# 6. 화면 하단 안내
# ---------------------------------------------------------
st.divider()
st.caption(
    "주의: 현재 버전은 학습용 화면입니다. "
    "코레일 로그인, 실제 좌석 조회, 자동 예매 기능은 포함되어 있지 않습니다."
)
