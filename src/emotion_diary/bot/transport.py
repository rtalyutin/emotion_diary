"""Telegram transport utilities used by the Emotion Diary bot."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

from emotion_diary.event_bus import Event, EventBus

logger = logging.getLogger(__name__)


class TelegramAPIError(RuntimeError):
    """Raised when Telegram API returns an error response."""


class TelegramAPI:
    """Minimal asynchronous Telegram Bot API client."""

    def __init__(
        self, token: str, *, base_url: str | None = None, timeout: float = 10.0
    ) -> None:  # pragma: no cover - runtime-only configuration
        """Configure the Telegram Bot API client.

        Args:
            token: Bot token issued by Telegram.
            base_url: Optional alternative API base URL.
            timeout: Request timeout in seconds for blocking calls.

        Raises:
            ValueError: If the token is empty.

        """
        if not token:
            raise ValueError("Telegram bot token must be provided")
        self.token = token
        self.base_url = base_url or f"https://api.telegram.org/bot{token}/"
        if not self.base_url.endswith("/"):
            self.base_url += "/"
        self.timeout = timeout

    async def call_method(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> Any:  # pragma: no cover - performs real HTTP requests
        """Invoke an arbitrary Telegram Bot API method.

        Args:
            method: Name of the API method.
            params: JSON-serialisable parameters for the call.
            files: Optional mapping describing files to upload.

        Returns:
            Parsed ``result`` portion of the API response.

        Raises:
            TelegramAPIError: If Telegram reports an error response.

        """
        url = f"{self.base_url}{method}"
        payload = dict(params or {})
        headers: dict[str, str] = {}
        data: bytes
        if files:
            boundary, data = _encode_multipart_formdata(payload, files)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"

        def _sync_request() -> Any:
            """Perform the blocking HTTP request in a thread."""
            req = urlrequest.Request(url, data=data, headers=headers, method="POST")
            with urlrequest.urlopen(
                req, timeout=self.timeout
            ) as response:  # nosec B310 - Telegram API over HTTPS
                body = response.read().decode("utf-8")
            parsed = json.loads(body)
            if not parsed.get("ok"):
                raise TelegramAPIError(parsed.get("description", "Telegram API error"))
            return parsed.get("result")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_request)

    async def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
        allowed_updates: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:  # pragma: no cover - requires Telegram API
        """Fetch updates from Telegram for long polling bots.

        Args:
            offset: Optional offset to resume from the last update ID.
            timeout: Long polling timeout in seconds.
            allowed_updates: Optional list of update types to receive.

        Returns:
            List of updates represented as dictionaries.

        """
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates is not None:
            params["allowed_updates"] = list(allowed_updates)
        result = await self.call_method("getUpdates", params)
        return list(result or [])

    async def send_message(
        self, chat_id: int | str, text: str, **extra: Any
    ) -> Any:  # pragma: no cover - delegates to network call
        """Send a text message via the Telegram Bot API."""
        params = {"chat_id": chat_id, "text": text, **extra}
        return await self.call_method("sendMessage", params)

    async def send_photo(
        self,
        chat_id: int | str,
        photo: str,
        *,
        caption: str | None = None,
        parse_mode: str | None = None,
        **extra: Any,
    ) -> Any:  # pragma: no cover - delegates to network call
        """Send a photo to the user, uploading if necessary."""
        params: dict[str, Any] = {"chat_id": chat_id, **extra}
        if caption:
            params["caption"] = caption
        if parse_mode:
            params["parse_mode"] = parse_mode

        files: dict[str, tuple[str, bytes, str]] | None = None
        photo_path = Path(photo)
        if photo_path.exists() and photo_path.is_file():
            content = photo_path.read_bytes()
            files = {"photo": (photo_path.name, content, "application/octet-stream")}
        else:
            params["photo"] = photo
        return await self.call_method("sendPhoto", params, files=files)


def _encode_multipart_formdata(
    fields: Mapping[str, Any],
    files: Mapping[str, tuple[str, bytes, str]],
) -> tuple[str, bytes]:  # pragma: no cover - helper for network requests
    """Encode payload and files into multipart/form-data."""
    boundary = os.urandom(16).hex()
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        if isinstance(value, bytes):
            body.extend(value)
        else:
            body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, (filename, content, content_type) in files.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return boundary, bytes(body)


def _extract_message_fields(message: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalised fields derived from a Telegram message payload."""

    fields: dict[str, Any] = {}
    chat = message.get("chat")
    if isinstance(chat, Mapping):
        chat_id = chat.get("id")
        if chat_id is not None:
            fields["chat_id"] = chat_id
    if "text" in message:
        fields["text"] = message.get("text")
    if "message_id" in message:
        fields["message_id"] = message.get("message_id")

    ts = message.get("date")
    parsed_ts = _parse_timestamp(ts)
    if parsed_ts is not None:
        fields["ts"] = parsed_ts

    return fields


def _extract_callback_fields(callback: Mapping[str, Any]) -> dict[str, Any]:
    """Return fields derived from a Telegram callback query payload."""

    fields: dict[str, Any] = {}
    data = callback.get("data")
    if data is not None:
        fields["callback_data"] = data

    message = callback.get("message")
    if isinstance(message, Mapping):
        fields.update(_extract_message_fields(message))

    from_user = callback.get("from")
    if isinstance(from_user, Mapping):
        from_id = from_user.get("id")
        if from_id is not None:
            fields.setdefault("from_id", from_id)

    return fields


def _parse_timestamp(value: Any) -> datetime | None:
    """Convert Telegram ``date`` fields to :class:`datetime` instances."""

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def normalize_update(update: Mapping[str, Any]) -> dict[str, Any]:
    """Convert Telegram update payload to internal ``tg.update`` structure."""

    payload: dict[str, Any] = {
        "update_id": update.get("update_id"),
        "raw": dict(update),
    }

    for key in ("message", "edited_message"):
        candidate = update.get(key)
        if isinstance(candidate, Mapping):
            payload.update(_extract_message_fields(candidate))

    callback = update.get("callback_query")
    if isinstance(callback, Mapping):
        payload.update(_extract_callback_fields(callback))

    payload.setdefault("ts", datetime.now(UTC))
    return payload


@dataclass
class TelegramResponder:
    """Subscribe to ``tg.response`` and send payloads to Telegram."""

    bus: EventBus
    api: TelegramAPI

    def __post_init__(self) -> None:
        """Subscribe to the event bus for outgoing responses."""
        self.bus.subscribe("tg.response", self.handle)

    async def handle(self, event: Event) -> None:
        """Send ``tg.response`` payloads to Telegram.

        Args:
            event: Event emitted by the internal bus.

        """
        payload = dict(event.payload)
        payload.pop("created_at", None)
        method = payload.pop("method", None)
        files = payload.pop("files", None)
        document_path = payload.pop("document_path", None)
        if method:
            if method == "sendDocument" and document_path and files is None:
                doc_path = Path(document_path)
                if doc_path.exists() and doc_path.is_file():
                    files = {
                        "document": (
                            doc_path.name,
                            doc_path.read_bytes(),
                            "application/octet-stream",
                        )
                    }
            await self.api.call_method(method, payload, files=files)
            return
        chat_id = payload.pop("chat_id", None)
        if chat_id is None:  # pragma: no cover - defensive logging
            logger.debug("TelegramResponder got payload without chat_id: %s", payload)
            return
        text = payload.pop("text", None)
        sprite = payload.pop("sprite", None)
        if sprite:
            await self.api.send_photo(chat_id, sprite, caption=text, **payload)
        elif text:
            await self.api.send_message(chat_id, text, **payload)
        else:  # pragma: no cover - defensive logging
            logger.debug(
                "TelegramResponder payload has neither text nor sprite: %s", payload
            )


async def run_polling(
    bus: EventBus,
    api: TelegramAPI,
    *,
    poll_timeout: int = 30,
    idle_delay: float = 1.0,
) -> None:
    """Continuously fetch updates from Telegram and publish them to the bus.

    Args:
        bus: Event bus used by the application.
        api: Telegram API client to poll for updates.
        poll_timeout: Long polling timeout in seconds.
        idle_delay: Sleep duration between empty polling attempts.

    """
    logger.info("Starting polling loop")
    offset: int | None = None
    try:
        while True:
            try:
                updates = await api.get_updates(offset=offset, timeout=poll_timeout)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Polling failed, retrying")
                await asyncio.sleep(min(idle_delay, 5.0))
                continue
            if updates:
                for update in updates:
                    payload = normalize_update(update)
                    update_id = payload.get("update_id")
                    if isinstance(update_id, int):
                        offset = max(offset or 0, update_id + 1)
                    await bus.publish(
                        "tg.update",
                        payload=payload,
                        metadata={"transport": "polling"},
                    )
            else:
                await asyncio.sleep(idle_delay)
    except asyncio.CancelledError:  # pragma: no cover - graceful shutdown
        logger.info("Polling loop cancelled")
        raise


class WebhookServer:
    """Minimal HTTP server to accept Telegram webhook updates."""

    def __init__(self, host: str, port: int, secret: str, bus: EventBus) -> None:
        """Store webhook configuration and prepare server state."""
        self.host = host
        self.port = port
        self.secret = secret
        self.bus = bus
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:  # pragma: no cover - requires real sockets
        """Start listening for incoming webhook requests."""
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        sockets = getattr(self._server, "sockets", None)
        if sockets:
            sock = sockets[0].getsockname()
            logger.info("Webhook server listening on %s:%s", sock[0], sock[1])

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:  # pragma: no cover - exercised with real sockets
        """Read an HTTP request and dispatch it to :meth:`process_request`."""
        try:
            request = await self._read_request(reader)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to read webhook request")
            writer.close()
            await writer.wait_closed()
            return
        if request is None:
            writer.close()
            await writer.wait_closed()
            return
        method, headers, body = request
        status, response_body = await self.process_request(method, headers, body)
        response = self._format_response(status, response_body)
        writer.write(response)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def _read_request(
        self, reader: asyncio.StreamReader
    ) -> tuple[str, dict[str, str], bytes] | None:  # pragma: no cover
        """Read a minimal HTTP request from the stream."""
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = await reader.read(1024)
            if not chunk:
                break
            data += chunk
        if not data:
            return None
        headers_part, _, remainder = data.partition(b"\r\n\r\n")
        try:
            header_lines = headers_part.decode("iso-8859-1").split("\r\n")
            request_line = header_lines[0]
            method, _path, _protocol = request_line.split(" ", 2)
        except Exception:
            return None
        headers: dict[str, str] = {}
        for line in header_lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers.get("content-length", "0"))
        body = remainder
        missing = content_length - len(body)
        if missing > 0:
            body += await reader.readexactly(missing)
        return method.upper(), headers, body

    async def process_request(
        self, method: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        """Validate incoming webhook requests and publish events."""
        if method != "POST":
            return 405, b""
        token = headers.get("x-telegram-bot-api-secret-token")
        if not token or token != self.secret:
            return 403, b""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return 400, b""
        await self.bus.publish(
            "tg.update",
            payload=normalize_update(payload),
            metadata={"transport": "webhook"},
        )
        return 200, b"{}"

    async def stop(self) -> None:  # pragma: no cover - requires running server
        """Stop the HTTP server if it is running."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def serve_forever(self) -> None:  # pragma: no cover - long running loop
        """Block until the server is cancelled."""
        if self._server is None:
            raise RuntimeError("Server is not started")
        async with self._server:
            await self._server.serve_forever()

    @staticmethod
    def _format_response(status: int, body: bytes) -> bytes:  # pragma: no cover
        """Construct a raw HTTP response body."""
        reason = {
            200: "OK",
            400: "Bad Request",
            403: "Forbidden",
            405: "Method Not Allowed",
        }.get(status, "OK")
        payload = body or b""
        headers = [
            f"HTTP/1.1 {status} {reason}",
            f"Content-Length: {len(payload)}",
            "Connection: close",
        ]
        if payload:
            headers.append("Content-Type: application/json")
        headers.append("")
        headers.append("")
        response = "\r\n".join(headers).encode("utf-8") + payload
        return response


async def run_webhook(
    host: str,
    port: int,
    bus: EventBus,
    *,
    secret: str,
) -> None:  # pragma: no cover - orchestrates real HTTP server
    """Run webhook HTTP server until cancelled.

    Args:
        host: Interface the server should bind to.
        port: TCP port for incoming connections.
        bus: Event bus to publish updates to.
        secret: Shared secret used to validate requests.

    """
    server = WebhookServer(host, port, secret, bus)
    await server.start()
    try:
        await server.serve_forever()
    except asyncio.CancelledError:  # pragma: no cover - graceful shutdown
        logger.info("Webhook loop cancelled")
        raise
    finally:
        await server.stop()
