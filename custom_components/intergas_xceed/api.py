"""Async HTTP client for the Intergas XCeed / heatapp! local server."""

from __future__ import annotations

import asyncio
from base64 import b64decode
from dataclasses import dataclass
from hashlib import md5, sha256
import json
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
from Cryptodome.Cipher import AES

from .const import (
    DEFAULT_DEVICE_NAME,
    DEFAULT_UDID,
    DEVICE_TOKEN_IV_B64,
    ENDPOINT_CHALLENGE,
    ENDPOINT_RESPONSE,
    ENDPOINT_ROOM_LIST,
    ENDPOINT_ROOM_SET_TEMPERATURE,
    ENDPOINT_SCENE_SET,
    ENDPOINT_SCENE_STATUS,
    ENDPOINT_SWITCHING_TIMES_GET,
    ENDPOINT_SYSTEM_STATE,
    ENDPOINT_VERSION,
    ENDPOINT_WEATHER,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class IntergasXceedApiError(Exception):
    """Raised when the device API returns an unexpected result."""


class IntergasXceedAuthenticationError(IntergasXceedApiError):
    """Raised when authentication fails."""


class IntergasXceedInvalidAuthError(IntergasXceedAuthenticationError):
    """Raised when the device explicitly rejects the supplied credentials."""


@dataclass
class _Session:
    """Authenticated session state."""

    user_id: str
    device_token: str


class IntergasXceedApiClient:
    """Thin async client around the reverse-engineered local heatapp! API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: ClientSession,
    ) -> None:
        self._host = host
        self._username = username
        self._password = password
        self._session = session
        self._auth: _Session | None = None
        self._counter = 0
        self._auth_lock = asyncio.Lock()

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    # ------------------------------------------------------------------
    # Public high level API
    # ------------------------------------------------------------------
    async def async_test_connection(self) -> dict[str, Any]:
        """Validate credentials and return device version information."""
        try:
            await self._async_authenticate()
            return await self._async_signed_request(ENDPOINT_VERSION)
        except IntergasXceedApiError:
            _LOGGER.exception(
                "Intergas XCeed test connection failed for host %s", self._host
            )
            raise

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch the full read model from the device."""
        await self._async_authenticate()

        version, rooms, scenes, systemstate, weather = await asyncio.gather(
            self._safe_request(ENDPOINT_VERSION),
            self._safe_request(ENDPOINT_ROOM_LIST),
            self._safe_request(ENDPOINT_SCENE_STATUS),
            self._safe_request(ENDPOINT_SYSTEM_STATE),
            self._safe_request(ENDPOINT_WEATHER),
        )

        if rooms is None:
            raise IntergasXceedApiError("Device did not return a room list")

        room_ids: list[int] = []
        for group in rooms.get("groups") or []:
            for room in group.get("rooms") or []:
                if room.get("id") is not None:
                    room_ids.append(int(room["id"]))

        schedule_results = await asyncio.gather(
            *(
                self._safe_request(ENDPOINT_SWITCHING_TIMES_GET, {"roomid": rid})
                for rid in room_ids
            )
        )
        schedules: dict[int, Any] = {}
        for rid, result in zip(room_ids, schedule_results):
            if result and result.get("switchingtimes") is not None:
                schedules[rid] = result["switchingtimes"]

        return {
            "version": version or {},
            "rooms": rooms,
            "scenes": scenes or {},
            "systemstate": systemstate or {},
            "weather": weather or {},
            "schedules": schedules,
        }

    async def async_set_room_temperature(
        self, room_id: int, temperature: float, change_mode: int = 0
    ) -> None:
        """Set the desired temperature for a room/zone.

        Heating zones accept ``change_mode=0`` (override until the next
        switch point); the domestic hot water circuit rejects mode 0 with a
        ``heatcom_error`` and requires ``change_mode=1``.
        """
        if float(temperature).is_integer():
            value: float | int = int(temperature)
        else:
            value = round(float(temperature), 1)
        result = await self._async_signed_request(
            ENDPOINT_ROOM_SET_TEMPERATURE,
            {
                "roomid": int(room_id),
                "change_mode": int(change_mode),
                "temperature": value,
            },
        )
        if result.get("success") is False:
            raise IntergasXceedApiError(
                "Setting the temperature failed: "
                f"{result.get('message') or 'unknown error'}"
            )

    async def async_set_scene(
        self, scene: str, active: bool, duration: int = 1
    ) -> None:
        """Activate or deactivate a heatapp! scene (operating mode)."""
        result = await self._async_signed_request(
            ENDPOINT_SCENE_SET,
            {"scene": scene, "active": 1 if active else 0, "duration": int(duration)},
        )
        if result.get("success") is False:
            raise IntergasXceedApiError(
                f"Setting scene {scene} failed: {result.get('message') or 'unknown error'}"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _safe_request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Run a signed request, returning None on a per-endpoint failure."""
        try:
            return await self._async_signed_request(path, payload)
        except IntergasXceedApiError as err:
            _LOGGER.debug("Intergas XCeed request to %s failed: %s", path, err)
            return None

    async def _async_authenticate(self) -> None:
        """Log in and cache the decrypted device token."""
        async with self._auth_lock:
            if self._auth is not None:
                return

            challenge = await self._request_form(
                ENDPOINT_CHALLENGE, {"udid": DEFAULT_UDID}
            )
            nonce = challenge.get("devicetoken")
            if not nonce:
                _LOGGER.error(
                    "Intergas XCeed host %s returned no challenge nonce: %s",
                    self._host,
                    challenge,
                )
                raise IntergasXceedApiError("Challenge nonce missing from response")

            hashed = md5(
                f"{self._password}{nonce}".encode("utf-8"), usedforsecurity=False
            ).hexdigest()
            login = await self._request_form(
                ENDPOINT_RESPONSE,
                {
                    "login": self._username,
                    "devicename": DEFAULT_DEVICE_NAME,
                    "token": nonce,
                    "hashed": hashed,
                    "udid": DEFAULT_UDID,
                },
            )

            if login.get("loginRejected") or not login.get("success", True):
                _LOGGER.error(
                    "Intergas XCeed host %s rejected login for user %s",
                    self._host,
                    self._username,
                )
                raise IntergasXceedInvalidAuthError(
                    "The device rejected the supplied credentials"
                )

            encrypted = login.get("devicetoken_encrypted")
            user_id = login.get("userid")
            if not encrypted or user_id is None:
                _LOGGER.error(
                    "Intergas XCeed host %s returned an incomplete login response",
                    self._host,
                )
                raise IntergasXceedApiError("Login response is missing token information")

            self._auth = _Session(
                user_id=str(user_id),
                device_token=self._decrypt_device_token(str(encrypted)),
            )
            self._counter = 0
            _LOGGER.debug("Authenticated against Intergas XCeed at %s", self._host)

    async def _async_signed_request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Issue a signed request, re-authenticating once on rejection."""
        await self._async_authenticate()
        if self._auth is None:
            raise IntergasXceedAuthenticationError("Authentication state is missing")

        params: dict[str, Any] = {
            "udid": DEFAULT_UDID,
            "reqcount": self._next_counter(),
            "userid": self._auth.user_id,
        }
        if payload:
            params.update(payload)
        params["request_signature"] = self._create_signature(params)

        response = await self._request_form(path, params)
        if response.get("loginRejected"):
            self._auth = None
            await self._async_authenticate()
            return await self._async_signed_request(path, payload)
        return response

    def _next_counter(self) -> int:
        """Return the next request counter value (0-based, like the app)."""
        value = self._counter
        self._counter += 1
        return value

    def _create_signature(self, params: dict[str, Any]) -> str:
        """Create the md5 request signature the API expects."""
        if self._auth is None:
            raise IntergasXceedAuthenticationError("Cannot sign without a session")
        message = "".join(
            f"{key}={_normalize(params[key])}|"
            for key in sorted(params)
            if key != "request_signature"
        )
        return md5(
            f"{message}{self._auth.device_token}".encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()

    async def _request_form(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Issue a form-encoded POST request and parse the JSON response."""
        url = f"http://{self._host}{path}"
        try:
            async with self._session.post(
                url,
                data={key: _normalize(value) for key, value in payload.items()},
                headers={"X-Requested-With": "XMLHttpRequest"},
                timeout=REQUEST_TIMEOUT,
            ) as response:
                text = await response.text()
        except (ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error(
                "Intergas XCeed request failed for host %s path %s: %s",
                self._host,
                path,
                err,
            )
            raise IntergasXceedApiError(f"Request to {path} failed: {err}") from err

        if response.status >= 400:
            raise IntergasXceedApiError(
                f"Request to {path} failed with HTTP {response.status}"
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as err:
            raise IntergasXceedApiError(
                f"Request to {path} did not return valid JSON"
            ) from err

        if not isinstance(data, dict):
            raise IntergasXceedApiError(f"Request to {path} returned a non-object payload")
        return data

    def _decrypt_device_token(self, encrypted_token: str) -> str:
        """Decrypt the AES-256-CBC encrypted device token."""
        key = sha256(self._password.encode("utf-8")).digest()
        iv = b64decode(DEVICE_TOKEN_IV_B64)
        encrypted_bytes = b64decode(encrypted_token)
        decrypted = AES.new(key, AES.MODE_CBC, iv).decrypt(encrypted_bytes)
        padding_length = decrypted[-1]
        if padding_length < 1 or padding_length > AES.block_size:
            raise IntergasXceedAuthenticationError(
                "Received an invalid encrypted device token"
            )
        return decrypted[:-padding_length].decode("utf-8")


def _normalize(value: Any) -> str:
    """Normalise a value for the request body and signature."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
