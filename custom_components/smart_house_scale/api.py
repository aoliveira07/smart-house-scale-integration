"""Small HTTP client for the central API; secrets never enter logs."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib import error, request

_LOGGER = logging.getLogger(__name__)


class ScaleApiClient:
    def __init__(self, base_url: str, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.last_attempt: str | None = None
        self.last_success: str | None = None
        self.last_error: str | None = None

    async def post_measurement(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._post, "/api/v1/scale-measurements", payload)

    async def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        return await asyncio.to_thread(self._request, method, path, payload)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.last_attempt = payload.get("received_at") if payload else datetime.now(UTC).isoformat()
        try:
            req = request.Request(self.base_url + path, data=body, headers=headers, method=method)
            with request.urlopen(req, timeout=8) as response:
                value = json.loads(response.read().decode("utf-8"))
            self.last_success = self.last_attempt
            self.last_error = None
            return value
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            self.last_error = type(exc).__name__
            raise
