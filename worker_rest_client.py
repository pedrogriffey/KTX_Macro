from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests


class WorkerAPIError(RuntimeError):
    """Supabase REST API 또는 RPC 호출 오류입니다."""


class SupabaseWorkerClient:
    def __init__(
        self,
        supabase_url: str,
        secret_key: str,
        timeout: int = 20,
    ) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.secret_key = secret_key.strip()
        self.timeout = timeout

        if not self.supabase_url:
            raise WorkerAPIError(
                "SUPABASE_URL이 비어 있습니다."
            )

        if not self.secret_key:
            raise WorkerAPIError(
                "SUPABASE_SECRET_KEY가 비어 있습니다."
            )

        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": self.secret_key,
                "Content-Type": "application/json",
                "User-Agent": "ktx-seat-worker/7A",
            }
        )

        # Legacy service_role JWT는 Authorization 헤더도 사용합니다.
        # 새 sb_secret_ 키는 apikey 헤더에만 넣습니다.
        if self.secret_key.startswith("eyJ"):
            self.session.headers.update(
                {
                    "Authorization": (
                        f"Bearer {self.secret_key}"
                    )
                }
            )

    def rpc(
        self,
        function_name: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        url = (
            f"{self.supabase_url}/rest/v1/rpc/"
            f"{quote(function_name)}"
        )

        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout,
        )

        data = self._decode_response(response)

        if data is None:
            return []

        if isinstance(data, list):
            return [
                row
                for row in data
                if isinstance(row, dict)
            ]

        if isinstance(data, dict):
            return [data]

        return []

    def get_profile(
        self,
        user_id: str,
    ) -> dict[str, Any] | None:
        url = f"{self.supabase_url}/rest/v1/profiles"

        response = self.session.get(
            url,
            params={
                "id": f"eq.{user_id}",
                "select": (
                    "id,email,telegram_chat_id,"
                    "telegram_display_name"
                ),
                "limit": 1,
            },
            timeout=self.timeout,
        )

        data = self._decode_response(response)

        if isinstance(data, list) and data:
            row = data[0]
            if isinstance(row, dict):
                return row

        return None

    def update_job(
        self,
        job_id: str,
        lock_token: str,
        values: dict[str, Any],
    ) -> dict[str, Any] | None:
        url = (
            f"{self.supabase_url}/rest/v1/monitor_jobs"
        )

        response = self.session.patch(
            url,
            params={
                "id": f"eq.{job_id}",
                "lock_token": f"eq.{lock_token}",
            },
            json=values,
            headers={
                "Prefer": "return=representation",
            },
            timeout=self.timeout,
        )

        data = self._decode_response(response)

        if isinstance(data, list) and data:
            row = data[0]
            if isinstance(row, dict):
                return row

        return None

    def upsert_heartbeat(
        self,
        payload: dict[str, Any],
    ) -> None:
        url = (
            f"{self.supabase_url}"
            "/rest/v1/worker_heartbeats"
        )

        response = self.session.post(
            url,
            params={
                "on_conflict": "worker_id",
            },
            json=payload,
            headers={
                "Prefer": (
                    "resolution=merge-duplicates,"
                    "return=minimal"
                ),
            },
            timeout=self.timeout,
        )

        self._decode_response(response)

    @staticmethod
    def _decode_response(
        response: requests.Response,
    ) -> Any:
        if response.status_code >= 400:
            preview = response.text[:500]
            raise WorkerAPIError(
                f"Supabase API 오류 "
                f"(HTTP {response.status_code}): {preview}"
            )

        if response.status_code == 204:
            return None

        if not response.text.strip():
            return None

        try:
            return response.json()
        except ValueError as exc:
            raise WorkerAPIError(
                "Supabase 응답을 JSON으로 해석하지 못했습니다."
            ) from exc
