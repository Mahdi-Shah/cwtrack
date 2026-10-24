"""Credential protection and resumable platform authentication challenges."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import uuid
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .diagnostics import is_failure_kind


class WindowsDPAPIVault:
    """Protect small private records with the current Windows user's DPAPI key."""

    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser().resolve()

    def put(self, key: str, value: dict) -> None:
        if os.name != "nt":
            raise OSError("Windows protected storage is unavailable")
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = _dpapi(payload, protect=True)
        target = self._path(key)
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name("." + target.name + ".tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def get(self, key: str) -> dict | None:
        if os.name != "nt":
            raise OSError("Windows protected storage is unavailable")
        target = self._path(key)
        if not target.is_file():
            return None
        try:
            payload = _dpapi(target.read_bytes(), protect=False)
            result = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("protected record could not be read") from exc
        if not isinstance(result, dict):
            raise ValueError("protected record has an invalid shape")
        return result

    def delete(self, key: str) -> None:
        if os.name != "nt":
            raise OSError("Windows protected storage is unavailable")
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not key:
            raise ValueError("protected record key is required")
        name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".bin"
        return self._root / name


class AccessManager:
    """Coordinate external adapters while keeping credentials and sessions private."""

    def __init__(
        self,
        paths: dict,
        *,
        adapters: dict,
        vault,
        clock: Callable[[], str],
    ):
        if not isinstance(paths, dict) or not paths.get("home"):
            raise ValueError("AccessManager requires an explicit home path")
        if not isinstance(adapters, dict):
            raise ValueError("platform adapter factories are required")
        if vault is None:
            raise ValueError("protected state adapter is required")
        self._root = Path(paths["home"]).expanduser().resolve() / "access"
        self._manifest = self._root / "registry.json"
        self._adapters = adapters
        self._vault = vault
        self._clock = clock

    def configure(
        self, platform: str, origin: str, credentials: dict, *, label: str | None = None
    ) -> dict:
        """Store supplied credentials without writing or returning their values."""
        parsed = urlparse(origin) if isinstance(origin, str) else None
        if (
            not isinstance(platform, str)
            or not platform.strip()
            or parsed is None
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not isinstance(credentials, dict)
            or set(credentials) != {"username", "password"}
            or not all(isinstance(credentials[key], str) and credentials[key] for key in credentials)
        ):
            return {"status": "invalid_input"}
        if platform not in self._adapters:
            return {"status": "adapter_unavailable"}
        if label is not None and (
            not isinstance(label, str) or not label.strip() or len(label.strip()) > 80
        ):
            return {"status": "invalid_input"}
        allowed_hosts = {"cw": "cw.sharif.ir", "quera": "quera.org"}
        if platform in allowed_hosts and (
            parsed.scheme != "https"
            or parsed.hostname != allowed_hosts[platform]
            or parsed.port is not None
        ):
            return {"status": "invalid_input"}

        manifest = self._read()
        if label is not None and any(
            connection.get("state") == "configured"
            and connection.get("label", "").casefold() == label.strip().casefold()
            for connection in manifest["connections"].values()
        ):
            return {"status": "label_conflict"}
        connection_id = uuid.uuid4().hex
        connection = {
            "id": connection_id,
            "platform": platform.strip(),
            "origin": "{}://{}".format(parsed.scheme, parsed.netloc),
            "credential_generation": 1,
            "created_at": self._clock(),
            "state": "configured",
        }
        if label is not None:
            connection["label"] = label.strip()
        try:
            self._vault.put(_credential_key(connection_id, 1), credentials)
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        manifest["connections"][connection_id] = connection
        try:
            self._write(manifest)
        except OSError:
            self._vault.delete(_credential_key(connection_id, 1))
            return {"status": "unavailable"}
        return {
            "status": "ok",
            "connection_id": connection_id,
            "platform": connection["platform"],
            "credential_generation": connection["credential_generation"],
        }

    def forget(self, connection_id: str) -> dict:
        """Forget secrets and invalidate pending challenges without deleting work."""
        manifest = self._read()
        connection = manifest["connections"].get(connection_id)
        if connection is None:
            return {"status": "not_found"}
        try:
            self._vault.delete(_credential_key(connection_id, connection["credential_generation"]))
            self._vault.delete("credentials:" + connection_id)
            self._vault.delete("session:" + connection_id)
            for continuation in manifest["continuations"].values():
                if continuation["connection_id"] == connection_id:
                    self._vault.delete("challenge:" + continuation["id"])
                    continuation["status"] = "invalidated"
            connection["state"] = "forgotten"
            connection["credential_generation"] += 1
            self._write(manifest)
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        return {"status": "ok", "connection_id": connection_id}

    def update_credentials(
        self, connection_id: str, credentials: dict, *, expected_generation: int
    ) -> dict:
        """Rotate credentials, invalidate the previous session and pending challenges."""
        if not _valid_credentials(credentials) or not _valid_generation(expected_generation):
            return {"status": "invalid_input"}
        manifest = self._read()
        connection = manifest["connections"].get(connection_id)
        if connection is None or connection.get("state") != "configured":
            return {"status": "not_found"}
        if connection.get("credential_generation") != expected_generation:
            return {
                "status": "conflict",
                "credential_generation": connection.get("credential_generation"),
            }
        next_generation = expected_generation + 1
        try:
            current_credentials = self._vault.get(
                _credential_key(connection_id, expected_generation)
            )
            if current_credentials is None:
                current_credentials = self._vault.get("credentials:" + connection_id)
            if not _valid_credentials(current_credentials):
                return {"status": "secure_store_unavailable"}
            if current_credentials["username"] != credentials["username"]:
                return {"status": "account_mismatch"}
            self._vault.put(_credential_key(connection_id, next_generation), credentials)
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        connection["credential_generation"] = next_generation
        try:
            for continuation in manifest["continuations"].values():
                if (
                    continuation["connection_id"] == connection_id
                    and continuation["status"] == "pending"
                ):
                    continuation["status"] = "invalidated"
                    self._vault.delete("challenge:" + continuation["id"])
            self._write(manifest)
            self._vault.delete(_credential_key(connection_id, expected_generation))
            self._vault.delete("credentials:" + connection_id)
            self._vault.delete("session:" + connection_id)
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        return {
            "status": "ok",
            "connection_id": connection_id,
            "credential_generation": next_generation,
        }

    def connections(self) -> list[dict]:
        """Return configured account metadata without touching protected values."""
        manifest = self._read()
        configured = [
            {
                "id": connection["id"],
                "platform": connection["platform"],
                "label": connection.get("label"),
                "origin": connection["origin"],
                "credential_generation": connection["credential_generation"],
                "created_at": connection["created_at"],
                "state": connection["state"],
            }
            for connection in manifest["connections"].values()
            if connection.get("state") == "configured"
        ]
        counts: dict[str, int] = {}
        for connection in configured:
            counts[connection["platform"]] = counts.get(connection["platform"], 0) + 1
            if not connection.get("label"):
                connection["label"] = "{} · اتصال {}".format(
                    connection["platform"].upper(), counts[connection["platform"]]
                )
        return configured

    def pending_challenges(self) -> list[dict]:
        """Return resumable challenge metadata for the local CLI/API caller."""
        manifest = self._read()
        by_id = {item["id"]: item for item in self.connections()}
        results = []
        for continuation in manifest["continuations"].values():
            connection = by_id.get(continuation.get("connection_id"))
            if continuation.get("status") != "pending" or connection is None:
                continue
            results.append({
                "continuation_id": continuation["id"],
                "platform": connection["platform"],
                "label": connection["label"],
                "kind": continuation.get("kind"),
                "display": continuation.get("display"),
                "expires_at": continuation.get("expires_at"),
                "scope": (continuation.get("request") or {}).get("scope"),
                "created_at": continuation.get("created_at", ""),
            })
        return results

    def update_label(self, connection_id: str, label: str) -> dict:
        """Rename a local connection without changing credentials or identity."""
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
            return {"status": "invalid_input"}
        manifest = self._read()
        connection = manifest["connections"].get(connection_id)
        if connection is None or connection.get("state") != "configured":
            return {"status": "not_found"}
        if any(
            other_id != connection_id
            and other.get("state") == "configured"
            and other.get("label", "").casefold() == label.strip().casefold()
            for other_id, other in manifest["connections"].items()
        ):
            return {"status": "label_conflict"}
        connection["label"] = label.strip()
        try:
            self._write(manifest)
        except OSError:
            return {"status": "unavailable"}
        return {"status": "ok", "label": connection["label"]}

    def update_label_by_name(self, current_label: str, label: str) -> dict:
        matches = [
            connection for connection in self.connections()
            if connection.get("label", "").casefold() == current_label.casefold()
        ]
        if len(matches) != 1:
            return {"status": "not_found" if not matches else "ambiguous"}
        return self.update_label(matches[0]["id"], label)

    def forget_by_name(self, label: str) -> dict:
        matches = [
            connection for connection in self.connections()
            if connection.get("label", "").casefold() == label.casefold()
        ]
        if len(matches) != 1:
            return {"status": "not_found" if not matches else "ambiguous"}
        return self.forget(matches[0]["id"])

    def update_credentials_by_name(self, label: str, credentials: dict) -> dict:
        matches = [
            connection for connection in self.connections()
            if connection.get("label", "").casefold() == label.casefold()
        ]
        if len(matches) != 1:
            return {"status": "not_found" if not matches else "ambiguous"}
        connection = matches[0]
        return self.update_credentials(
            connection["id"], credentials,
            expected_generation=connection["credential_generation"],
        )

    def observe(self, connection_id: str, request: dict) -> dict:
        """Begin one adapter operation, returning a resumable public challenge."""
        manifest = self._read()
        connection = manifest["connections"].get(connection_id)
        if connection is None or connection.get("state") != "configured":
            return {"status": "needs_credentials"}
        factory = self._adapters.get(connection["platform"])
        if factory is None:
            return {"status": "adapter_unavailable"}
        try:
            credentials = self._vault.get(
                _credential_key(connection_id, connection["credential_generation"])
            )
            if credentials is None:
                credentials = self._vault.get("credentials:" + connection_id)
            session = self._vault.get("session:" + connection_id) or {}
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        if not credentials:
            return {"status": "needs_credentials"}
        try:
            result = factory(connection).observe(
                request, {"credentials": credentials, "session": session}
            )
        except (ConnectionError, TimeoutError, OSError):
            return {"status": "unavailable"}
        return self._accept_adapter_result(manifest, connection, request, result)

    def continue_operation(self, continuation_id: str, response: dict) -> dict:
        """Resume exactly one saved challenge, or replay its completed receipt."""
        if not _valid_response(response):
            return {"status": "invalid_input"}
        manifest = self._read()
        continuation = manifest["continuations"].get(continuation_id)
        if continuation is None:
            return {"status": "not_found"}
        if continuation["status"] == "completed":
            return {
                "status": "ok",
                "connection_id": continuation["connection_id"],
                "receipt": continuation["receipt"],
            }
        if continuation["status"] == "invalidated":
            return {"status": "account_mismatch"}
        if continuation["status"] != "pending":
            return {"status": "challenge_expired"}
        connection = manifest["connections"].get(continuation["connection_id"])
        if (
            connection is None
            or connection.get("state") != "configured"
            or connection.get("credential_generation") != continuation["credential_generation"]
        ):
            return {"status": "account_mismatch"}
        if _is_expired(continuation["expires_at"], self._clock()):
            continuation["status"] = "expired"
            self._write(manifest)
            self._vault.delete("challenge:" + continuation_id)
            return {"status": "challenge_expired"}
        try:
            private_state = self._vault.get("challenge:" + continuation_id)
        except (OSError, ValueError):
            return {"status": "secure_store_unavailable"}
        if private_state is None:
            return {"status": "challenge_expired"}
        factory = self._adapters.get(connection["platform"])
        if factory is None:
            return {"status": "adapter_unavailable"}
        try:
            result = factory(connection).resume(private_state, response)
        except (ConnectionError, TimeoutError, OSError):
            return {"status": "unavailable"}
        return self._accept_adapter_result(
            manifest, connection, continuation["request"], result, continuation=continuation
        )

    def _accept_adapter_result(
        self, manifest: dict, connection: dict, request: dict, result: dict,
        *, continuation: dict | None = None,
    ) -> dict:
        if not isinstance(result, dict):
            return {"status": "unavailable"}
        public_result = {key: value for key, value in result.items() if key != "private_state"}
        if _contains_secret_key(public_result):
            return {"status": "unavailable"}
        status = result.get("status")
        if status == "challenge_required":
            challenge = result.get("challenge")
            private_state = result.get("private_state")
            if not _valid_challenge(challenge) or not isinstance(private_state, dict):
                return {"status": "unavailable"}
            if continuation is None:
                continuation_id = uuid.uuid4().hex
                continuation = {
                    "id": continuation_id,
                    "connection_id": connection["id"],
                    "credential_generation": connection["credential_generation"],
                    "request": request,
                    "status": "pending",
                    "attempt_revision": 1,
                }
                manifest["continuations"][continuation_id] = continuation
            else:
                continuation["attempt_revision"] += 1
            continuation.update({
                "kind": challenge["kind"],
                "display": challenge["display"],
                "expires_at": challenge["expires_at"],
                "status": "pending",
            })
            try:
                self._vault.put("challenge:" + continuation["id"], private_state)
                self._write(manifest)
            except (OSError, ValueError):
                return {"status": "secure_store_unavailable"}
            return {
                "status": "challenge_required",
                "continuation_id": continuation["id"],
                "challenge": {
                    "kind": continuation["kind"],
                    "display": continuation["display"],
                    "expires_at": continuation["expires_at"],
                    "attempt_revision": continuation["attempt_revision"],
                },
            }

        if status == "ok":
            observation = result.get("observation")
            private_state = result.get("private_state")
            if not isinstance(observation, dict) or _contains_secret_key(observation):
                return {"status": "unavailable"}
            if isinstance(private_state, dict):
                try:
                    self._vault.put("session:" + connection["id"], private_state)
                except (OSError, ValueError):
                    return {"status": "secure_store_unavailable"}
            receipt = observation
            if continuation is None:
                return {
                    "status": "ok",
                    "connection_id": connection["id"],
                    "receipt": receipt,
                }
            continuation["status"] = "completed"
            continuation["receipt"] = receipt
            try:
                self._write(manifest)
                self._vault.delete("challenge:" + continuation["id"])
            except (OSError, ValueError):
                return {"status": "secure_store_unavailable"}
            return {
                "status": "ok",
                "connection_id": connection["id"],
                "receipt": receipt,
            }

        if continuation is not None and status == "challenge_rejected":
            challenge = result.get("challenge")
            private_state = result.get("private_state")
            if _valid_challenge(challenge) and isinstance(private_state, dict):
                return self._accept_adapter_result(
                    manifest,
                    connection,
                    request,
                    {"status": "challenge_required", "challenge": challenge,
                     "private_state": private_state},
                    continuation=continuation,
                )
        if status in {
            "challenge_expired", "challenge_unavailable", "account_mismatch", "invalid_input"
        }:
            return {"status": status}
        failure_kind = result.get("failure_kind")
        if is_failure_kind(failure_kind):
            return {"status": "unavailable", "failure_kind": failure_kind}
        return {"status": "unavailable"}

    def _read(self) -> dict:
        if not self._manifest.is_file():
            return {"schema_version": 1, "connections": {}, "continuations": {}}
        manifest = json.loads(self._manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("access registry is invalid")
        manifest.setdefault("connections", {})
        manifest.setdefault("continuations", {})
        return manifest

    def _write(self, manifest: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._manifest.with_name(".registry.{}.tmp".format(uuid.uuid4().hex))
        try:
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._manifest)
        finally:
            if temporary.exists():
                temporary.unlink()


def default_vault(home: str | Path):
    """Return OS-protected storage, never a plaintext fallback."""
    if os.name != "nt":
        return None
    return WindowsDPAPIVault(Path(home).expanduser().resolve() / "access-vault")


def _dpapi(payload: bytes, *, protect: bool) -> bytes:
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    data_blob_pointer = ctypes.POINTER(DataBlob)
    crypt32.CryptProtectData.argtypes = [
        data_blob_pointer, wintypes.LPCWSTR, data_blob_pointer, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, data_blob_pointer,
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        data_blob_pointer, ctypes.POINTER(wintypes.LPWSTR), data_blob_pointer,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, data_blob_pointer,
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = ctypes.create_string_buffer(payload)
    source = DataBlob(len(payload), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = DataBlob()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "cwtrack protected state", None, None, None, 1,
            ctypes.byref(output),
        )
    else:
        description = wintypes.LPWSTR()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), ctypes.byref(description), None, None, None, 1,
            ctypes.byref(output),
        )
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows protected storage failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def _valid_response(response: dict) -> bool:
    if not isinstance(response, dict):
        return False
    kind = response.get("kind")
    if kind == "interactive_completed":
        return set(response) == {"kind", "value"} and response["value"] is True
    return (
        kind in {"otp", "readable_code"}
        and set(response) == {"kind", "value"}
        and isinstance(response["value"], str)
        and bool(response["value"].strip())
    )


def _valid_credentials(value) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"username", "password"}
        and all(isinstance(value[key], str) and value[key] for key in value)
    )


def _valid_generation(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _credential_key(connection_id: str, generation: int) -> str:
    return "credentials:{}:{}".format(connection_id, generation)


def _valid_challenge(challenge: dict) -> bool:
    if not isinstance(challenge, dict):
        return False
    return (
        challenge.get("kind") in {"otp", "readable_code", "interactive"}
        and isinstance(challenge.get("display"), (str, dict))
        and isinstance(challenge.get("expires_at"), str)
        and not _contains_secret_key(challenge)
    )


def _contains_secret_key(value) -> bool:
    forbidden = {
        "password", "passwd", "credential", "credentials", "cookie", "cookies",
        "token", "csrf", "private_state", "session",
    }
    if isinstance(value, dict):
        return any(
            str(key).lower() in forbidden or _contains_secret_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret_key(item) for item in value)
    return False


def _is_expired(expires_at: str, now: str) -> bool:
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if expires.tzinfo is None or current.tzinfo is None:
            return True
        return current >= expires
    except (AttributeError, TypeError, ValueError):
        return True
