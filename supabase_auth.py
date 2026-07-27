from __future__ import annotations

from typing import Any, MutableMapping

from supabase import Client, create_client


class SupabaseAuthError(RuntimeError):
    """사용자에게 표시할 Supabase 인증·프로필 오류입니다."""


AUTH_STATE_KEYS = (
    "sb_access_token",
    "sb_refresh_token",
    "sb_user_id",
    "sb_user_email",
)


def create_supabase_client(
    supabase_url: str,
    publishable_key: str,
) -> Client:
    if not supabase_url:
        raise SupabaseAuthError("SUPABASE_URL이 설정되지 않았습니다.")

    if not publishable_key:
        raise SupabaseAuthError(
            "SUPABASE_PUBLISHABLE_KEY가 설정되지 않았습니다."
        )

    return create_client(supabase_url, publishable_key)


def _get_value(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(obj, name, default)


def _save_session(
    state: MutableMapping[str, Any],
    session: Any,
    user: Any = None,
) -> None:
    if session is None:
        return

    access_token = _get_value(session, "access_token", "")
    refresh_token = _get_value(session, "refresh_token", "")
    session_user = user or _get_value(session, "user")

    if not access_token or not refresh_token:
        raise SupabaseAuthError(
            "Supabase 로그인 세션 토큰을 확인하지 못했습니다."
        )

    state["sb_access_token"] = str(access_token)
    state["sb_refresh_token"] = str(refresh_token)

    if session_user is not None:
        user_id = _get_value(session_user, "id", "")
        email = _get_value(session_user, "email", "")

        if user_id:
            state["sb_user_id"] = str(user_id)

        if email:
            state["sb_user_email"] = str(email)


def clear_auth_state(state: MutableMapping[str, Any]) -> None:
    for key in AUTH_STATE_KEYS:
        state.pop(key, None)


def restore_authenticated_client(
    supabase_url: str,
    publishable_key: str,
    state: MutableMapping[str, Any],
) -> tuple[Client, dict[str, str] | None]:
    """Session State의 토큰으로 인증 세션을 복원합니다."""

    client = create_supabase_client(
        supabase_url,
        publishable_key,
    )

    access_token = str(
        state.get("sb_access_token", "")
    ).strip()
    refresh_token = str(
        state.get("sb_refresh_token", "")
    ).strip()

    if not access_token or not refresh_token:
        clear_auth_state(state)
        return client, None

    try:
        response = client.auth.set_session(
            access_token,
            refresh_token,
        )
        session = _get_value(response, "session")
        user = (
            _get_value(response, "user")
            or _get_value(session, "user")
        )

        _save_session(state, session, user)

        if user is None:
            user_response = client.auth.get_user()
            user = _get_value(user_response, "user")

        if user is None:
            raise SupabaseAuthError(
                "로그인 사용자 정보를 확인하지 못했습니다."
            )

        user_id = str(_get_value(user, "id", "")).strip()
        email = str(_get_value(user, "email", "")).strip()

        if not user_id:
            raise SupabaseAuthError(
                "로그인 사용자 ID를 확인하지 못했습니다."
            )

        state["sb_user_id"] = user_id
        state["sb_user_email"] = email

        return client, {
            "id": user_id,
            "email": email,
        }

    except Exception:
        clear_auth_state(state)
        return client, None


def sign_in_with_password(
    supabase_url: str,
    publishable_key: str,
    state: MutableMapping[str, Any],
    email: str,
    password: str,
) -> tuple[Client, dict[str, str]]:
    client = create_supabase_client(
        supabase_url,
        publishable_key,
    )

    try:
        response = client.auth.sign_in_with_password(
            {
                "email": email.strip().lower(),
                "password": password,
            }
        )
    except Exception as exc:
        raise SupabaseAuthError(
            friendly_auth_error(exc)
        ) from exc

    session = _get_value(response, "session")
    user = _get_value(response, "user")

    if session is None or user is None:
        raise SupabaseAuthError(
            "로그인 세션을 생성하지 못했습니다."
        )

    _save_session(state, session, user)

    user_id = str(_get_value(user, "id", "")).strip()
    user_email = str(_get_value(user, "email", "")).strip()

    return client, {
        "id": user_id,
        "email": user_email,
    }


def sign_up_with_password(
    supabase_url: str,
    publishable_key: str,
    state: MutableMapping[str, Any],
    email: str,
    password: str,
) -> tuple[Client, dict[str, str] | None, bool]:
    """회원가입 결과로 (client, user, email_confirmation_required)를 반환합니다."""

    client = create_supabase_client(
        supabase_url,
        publishable_key,
    )

    try:
        response = client.auth.sign_up(
            {
                "email": email.strip().lower(),
                "password": password,
            }
        )
    except Exception as exc:
        raise SupabaseAuthError(
            friendly_auth_error(exc)
        ) from exc

    session = _get_value(response, "session")
    user = _get_value(response, "user")

    if user is None:
        raise SupabaseAuthError(
            "회원가입 사용자 정보를 확인하지 못했습니다."
        )

    user_id = str(_get_value(user, "id", "")).strip()
    user_email = str(_get_value(user, "email", "")).strip()

    if session is None:
        return (
            client,
            {
                "id": user_id,
                "email": user_email,
            },
            True,
        )

    _save_session(state, session, user)

    return (
        client,
        {
            "id": user_id,
            "email": user_email,
        },
        False,
    )


def sign_out(
    client: Client,
    state: MutableMapping[str, Any],
) -> None:
    try:
        client.auth.sign_out()
    except Exception:
        # 서버 로그아웃 요청이 실패해도 현재 브라우저 세션은 제거합니다.
        pass
    finally:
        clear_auth_state(state)


def ensure_profile(
    client: Client,
    user_id: str,
    email: str,
) -> dict[str, Any]:
    """프로필 트리거가 누락된 경우에도 본인 프로필을 보장합니다."""

    try:
        response = (
            client.table("profiles")
            .select(
                "id,email,telegram_chat_id,"
                "telegram_display_name,created_at,updated_at"
            )
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        profile = response.data
    except Exception as exc:
        raise SupabaseAuthError(
            "사용자 프로필을 불러오지 못했습니다. "
            "profiles 테이블과 RLS 정책을 확인하세요."
        ) from exc

    if profile:
        return profile

    try:
        response = (
            client.table("profiles")
            .upsert(
                {
                    "id": user_id,
                    "email": email,
                },
                on_conflict="id",
            )
            .execute()
        )
    except Exception as exc:
        raise SupabaseAuthError(
            "사용자 프로필을 생성하지 못했습니다."
        ) from exc

    rows = response.data or []
    if isinstance(rows, list) and rows:
        return rows[0]

    return {
        "id": user_id,
        "email": email,
        "telegram_chat_id": None,
        "telegram_display_name": None,
    }


def save_telegram_profile(
    client: Client,
    user_id: str,
    email: str,
    chat_id: str,
    display_name: str,
) -> dict[str, Any]:
    try:
        response = (
            client.table("profiles")
            .upsert(
                {
                    "id": user_id,
                    "email": email,
                    "telegram_chat_id": chat_id,
                    "telegram_display_name": display_name,
                },
                on_conflict="id",
            )
            .execute()
        )
    except Exception as exc:
        raise SupabaseAuthError(
            "텔레그램 연결정보를 저장하지 못했습니다."
        ) from exc

    rows = response.data or []
    if isinstance(rows, list) and rows:
        return rows[0]

    return {
        "id": user_id,
        "email": email,
        "telegram_chat_id": chat_id,
        "telegram_display_name": display_name,
    }


def clear_telegram_profile(
    client: Client,
    user_id: str,
) -> None:
    try:
        (
            client.table("profiles")
            .update(
                {
                    "telegram_chat_id": None,
                    "telegram_display_name": None,
                }
            )
            .eq("id", user_id)
            .execute()
        )
    except Exception as exc:
        raise SupabaseAuthError(
            "텔레그램 연결정보를 삭제하지 못했습니다."
        ) from exc


def friendly_auth_error(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()

    mappings = (
        (
            "invalid login credentials",
            "이메일 또는 비밀번호가 올바르지 않습니다.",
        ),
        (
            "email not confirmed",
            "이메일 인증을 완료한 뒤 로그인하세요.",
        ),
        (
            "user already registered",
            "이미 가입된 이메일입니다.",
        ),
        (
            "password should be at least",
            "비밀번호가 너무 짧습니다.",
        ),
        (
            "weak password",
            "더 강한 비밀번호를 사용하세요.",
        ),
        (
            "rate limit",
            "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
        ),
        (
            "signup is disabled",
            "현재 신규 회원가입이 비활성화되어 있습니다.",
        ),
        (
            "email address",
            "올바른 이메일 주소를 입력하세요.",
        ),
    )

    for keyword, friendly_message in mappings:
        if keyword in lowered:
            return friendly_message

    return f"Supabase 인증 오류: {message}"
