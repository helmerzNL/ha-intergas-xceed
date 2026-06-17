"""HTTP client for Intergas XCeed."""

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from hashlib import md5, sha256
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
from Cryptodome.Cipher import AES

from .const import DEFAULT_DEVICE_NAME, DEFAULT_UDID, DEVICE_TOKEN_IV_B64, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class IntergasXceedApiError(Exception):
    """Raised when the device API returns an unexpected result."""


class IntergasXceedAuthenticationError(IntergasXceedApiError):
    """Raised when authentication fails."""


@dataclass
class IntergasXceedSession:
    """Authenticated session details."""

    user_id: str
    device_token: str
    request_counter: int = 0


class IntergasXceedApiClient:
    """Thin async client around the reverse-engineered local API."""

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
        self._auth: IntergasXceedSession | None = None

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    async def async_test_connection(self) -> dict[str, Any]:
        """Validate credentials and fetch a small dashboard snapshot."""
        await self._async_authenticate()
        return await self.async_get_dashboard()

    async def async_get_dashboard(self) -> dict[str, Any]:
        """Return the current aggregated read model."""
        return {
            "system_information": await self.async_admin_request("/admin/systeminformation/get"),
            "network": await self.async_admin_request("/admin/network/info"),
            "datetime": await self.async_admin_request("/admin/datetime/get"),
            "portal": await self.async_admin_request("/admin/portal/get"),
            "parameter_progress": await self.async_admin_request("/admin/parameter/progress"),
        }

    async def async_admin_request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a signed admin endpoint."""
        await self._async_authenticate()

        if self._auth is None:
            raise IntergasXceedAuthenticationError("Authentication state is missing")

        request_payload = dict(payload or {})
        self._auth.request_counter += 1
        request_payload["reqcount"] = self._auth.request_counter
        request_payload["udid"] = DEFAULT_UDID
        request_payload["userid"] = self._auth.user_id
        request_payload["request_signature"] = self._create_signature(request_payload)

        response = await self._request_json("POST", path, request_payload)
        if self._looks_like_auth_failure(response):
            self._auth = None
            await self._async_authenticate()
            return await self.async_admin_request(path, payload)

        return response

    async def _async_authenticate(self) -> None:
        """Log in and cache the decrypted device token."""
        if self._auth is not None:
            return

        challenge_response = await self._request_json(
            "POST",
            "/api/user/token/challenge",
            {"udid": DEFAULT_UDID},
        )
        challenge_token = _first_present(
            challenge_response,
            ("challengeToken", "challenge_token", "token"),
        )
        if not challenge_token:
            raise IntergasXceedAuthenticationError("Challenge token missing from response")

        password_hash = md5(f"{self._password}{challenge_token}".encode("utf-8"), usedforsecurity=False).hexdigest()
        login_response = await self._request_json(
            "POST",
            "/api/user/token/response",
            {
                "login": self._username,
                "devicename": DEFAULT_DEVICE_NAME,
                "token": challenge_token,
                "hashed": password_hash,
                "udid": DEFAULT_UDID,
            },
        )

        if self._looks_like_auth_failure(login_response):
            raise IntergasXceedAuthenticationError("The device rejected the supplied credentials")

        encrypted_device_token = _first_present(
            login_response,
            ("devicetoken_encrypted", "deviceTokenEncrypted"),
        )
        user_id = _first_present(login_response, ("userid", "userId"))
        if not encrypted_device_token or not user_id:
            raise IntergasXceedAuthenticationError("Login response is missing token information")

        self._auth = IntergasXceedSession(
            user_id=str(user_id),
            device_token=self._decrypt_device_token(str(encrypted_device_token)),
        )
        _LOGGER.debug("Authenticated against Intergas XCeed at %s", self._host)

    async def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Issue a JSON request against the device."""
        url = f"http://{self._host}{path}"

        try:
            async with self._session.request(
                method,
                url,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except ClientError as err:
            raise IntergasXceedApiError(f"Request to {path} failed") from err
        except ValueError as err:
            raise IntergasXceedApiError(f"Request to {path} did not return JSON") from err

        if not isinstance(data, dict):
            raise IntergasXceedApiError(f"Request to {path} returned a non-object payload")

        return data

    def _create_signature(self, payload: dict[str, Any]) -> str:
        """Create the md5 signature the admin API expects."""
        if self._auth is None:
            raise IntergasXceedAuthenticationError("Cannot sign request without an auth session")

        message = "|".join(
            f"{key}={_normalize_signature_value(payload[key])}"
            for key in sorted(payload)
            if key != "request_signature"
        )
        return md5(f"{message}{self._auth.device_token}".encode("utf-8"), usedforsecurity=False).hexdigest()

    def _decrypt_device_token(self, encrypted_token: str) -> str:
        """Decrypt the device token returned by the login response."""
        key = sha256(self._password.encode("utf-8")).digest()
        iv = b64decode(DEVICE_TOKEN_IV_B64)
        encrypted_bytes = b64decode(encrypted_token)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_bytes)
        padding_length = decrypted[-1]
        if padding_length < 1 or padding_length > AES.block_size:
            raise IntergasXceedAuthenticationError("Received an invalid encrypted device token")
        return decrypted[:-padding_length].decode("utf-8")

    @staticmethod
    def _looks_like_auth_failure(payload: dict[str, Any]) -> bool:
        """Best-effort detection for auth failures."""
        candidates = {
            str(value).lower()
            for key, value in payload.items()
            if key.lower() in {"status", "result", "message", "error"}
        }
        return "loginrejected" in candidates or "authfailed" in candidates


def _first_present(payload: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    """Return the first present key from a response payload."""
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _normalize_signature_value(value: Any) -> str:
    """Normalize request values to the format the signature algorithm expects."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
