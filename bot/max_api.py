from __future__ import annotations

import os
from typing import Any, Iterable

import httpx
from dotenv import load_dotenv

load_dotenv()


class MaxAPIClient:
    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.token = token or os.getenv("MAX_TOKEN")
        self.api_url = (api_url or os.getenv("MAX_API_URL") or "https://platform-api.max.ru").rstrip("/")
        self.request_timeout = request_timeout

        if not self.token:
            raise RuntimeError("MAX_TOKEN is not set")

        self._client = httpx.AsyncClient(
            base_url=self.api_url,
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(request_timeout),
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            details = response.text.strip()
            if details:
                raise RuntimeError(
                    f"MAX API error {response.status_code} for {response.request.method} "
                    f"{response.request.url}: {details}"
                ) from exc
            raise

    async def get_updates(
        self,
        *,
        marker: int | None = None,
        types: Iterable[str] | None = None,
        limit: int = 100,
        timeout: int = 30,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)

        response = await self._client.get(
            "/updates",
            params=params,
            timeout=httpx.Timeout(timeout + 10),
        )
        self._raise_for_status(response)
        return response.json()

    async def edit_my_info(self, **fields: Any) -> dict[str, Any]:
        response = await self._client.patch("/me", json=fields)
        self._raise_for_status(response)
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        response = await self._client.get("/me")
        self._raise_for_status(response)
        return response.json()

    async def set_my_commands(
        self,
        commands: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await self.edit_my_info(commands=commands)

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        format: str | None = None,
        notify: bool = True,
        link: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        elif chat_id is not None:
            params["chat_id"] = chat_id
        else:
            raise ValueError("Either user_id or chat_id must be provided")

        body: dict[str, Any] = {
            "text": text,
            "attachments": attachments or [],
            "notify": notify,
        }
        if format:
            body["format"] = format
        if link:
            body["link"] = link

        response = await self._client.post("/messages", params=params, json=body)
        self._raise_for_status(response)
        return response.json()

    async def delete_message(self, message_id: str | int) -> dict[str, Any]:
        response = await self._client.delete(
            "/messages",
            params={"message_id": message_id},
        )
        self._raise_for_status(response)
        return response.json() if response.content else {}

    async def answer_callback(
        self,
        callback_id: str,
        *,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        notification: str | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}

        if text is not None or attachments is not None or format is not None:
            message: dict[str, Any] = {
                "text": text or "",
                "attachments": attachments or [],
            }
            if format:
                message["format"] = format
            body["message"] = message

        if notification:
            body["notification"] = notification

        if not body:
            raise ValueError("Callback answer must contain message and/or notification")

        response = await self._client.post(
            "/answers",
            params={"callback_id": callback_id},
            json=body,
        )
        self._raise_for_status(response)
        return response.json()
