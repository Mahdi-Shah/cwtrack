"""Public access flow tests using a stateful platform adapter and protected store."""

from __future__ import annotations

import pytest

from cwtrack.access import AccessManager, WindowsDPAPIVault


class MemoryVault:
    def __init__(self):
        self.values = {}
        self.unavailable = False

    def put(self, key, value):
        if self.unavailable:
            raise OSError("protected storage is unavailable")
        self.values[key] = value

    def get(self, key):
        if self.unavailable:
            raise OSError("protected storage is unavailable")
        return self.values.get(key)

    def delete(self, key):
        if self.unavailable:
            raise OSError("protected storage is unavailable")
        self.values.pop(key, None)


class ChallengeAdapter:
    def __init__(self, connection):
        self.connection = connection
        self.resume_calls = 0

    def observe(self, request, context):
        assert context["credentials"] == {
            "username": "student@example.test",
            "password": "not-a-real-password",
        }
        assert request == {"scope": "classes"}
        return {
            "status": "challenge_required",
            "challenge": {
                "kind": "otp",
                "display": "کد یک‌بارمصرف را وارد کن",
                "expires_at": "2026-10-17T12:10:00+03:30",
            },
            "private_state": {"cookie": "private-session-cookie"},
        }

    def resume(self, private_state, response):
        self.resume_calls += 1
        assert private_state == {"cookie": "private-session-cookie"}
        assert response == {"kind": "otp", "value": "123456"}
        return {
            "status": "ok",
            "observation": {
                "scope": "classes",
                "coverage": "complete",
                "nodes": [],
            },
            "private_state": {"cookie": "authenticated-cookie"},
        }


def make_manager(tmp_path, *, clock, vault=None):
    vault = vault or MemoryVault()
    adapters = {}
    instances = []

    def build(connection):
        adapter = ChallengeAdapter(connection)
        instances.append(adapter)
        return adapter

    adapters["quera"] = build
    return AccessManager(
        {"home": tmp_path}, adapters=adapters, vault=vault, clock=clock
    ), vault, instances


def test_challenge_continues_in_a_new_manager_and_duplicate_completion_is_safe(tmp_path):
    now = "2026-10-17T12:00:00+03:30"
    manager, vault, instances = make_manager(tmp_path, clock=lambda: now)
    configured = manager.configure(
        "quera",
        "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )
    started = manager.observe(configured["connection_id"], {"scope": "classes"})
    assert started["status"] == "challenge_required"
    assert started["challenge"]["kind"] == "otp"

    access_dir = tmp_path / "access"
    metadata_before = "".join(path.read_text(encoding="utf-8") for path in access_dir.glob("*.json"))
    assert "not-a-real-password" not in metadata_before
    assert "private-session-cookie" not in metadata_before
    assert "private_state" not in started

    resumed, _, resumed_instances = make_manager(tmp_path, clock=lambda: now, vault=vault)
    finished = resumed.continue_operation(
        started["continuation_id"], {"kind": "otp", "value": "123456"}
    )
    repeated = resumed.continue_operation(
        started["continuation_id"], {"kind": "otp", "value": "123456"}
    )

    assert finished == repeated
    assert finished["status"] == "ok"
    assert finished["receipt"]["scope"] == "classes"
    assert resumed_instances[0].resume_calls == 1
    assert instances[0].resume_calls == 0


def test_connections_support_unique_local_labels_and_legacy_generated_names(tmp_path):
    now = "2026-10-17T12:00:00+03:30"
    manager, _, _ = make_manager(tmp_path, clock=lambda: now)
    first = manager.configure(
        "quera", "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
        label="دانشگاه",
    )
    assert first["status"] == "ok"
    assert manager.connections()[0]["label"] == "دانشگاه"
    duplicate = manager.configure(
        "quera", "https://quera.org",
        {"username": "other@example.test", "password": "not-a-real-password"},
        label="دانشگاه",
    )
    assert duplicate["status"] == "label_conflict"
    legacy = manager.configure(
        "quera", "https://quera.org",
        {"username": "legacy@example.test", "password": "not-a-real-password"},
    )
    assert legacy["status"] == "ok"
    assert manager.connections()[1]["label"] == "QUERA · اتصال 2"
    renamed = manager.update_label_by_name("QUERA · اتصال 2", "دانشگاه دوم")
    assert renamed == {"status": "ok", "label": "دانشگاه دوم"}
    assert manager.connections()[1]["label"] == "دانشگاه دوم"


def test_expired_challenge_does_not_send_the_response_to_the_site(tmp_path):
    now = ["2026-10-17T12:00:00+03:30"]
    manager, _, instances = make_manager(tmp_path, clock=lambda: now[0])
    configured = manager.configure(
        "quera",
        "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )
    started = manager.observe(configured["connection_id"], {"scope": "classes"})
    now[0] = "2026-10-17T12:11:00+03:30"

    result = manager.continue_operation(
        started["continuation_id"], {"kind": "otp", "value": "123456"}
    )

    assert result["status"] == "challenge_expired"
    assert instances[-1].resume_calls == 0


def test_unavailable_protected_storage_never_falls_back_to_plaintext(tmp_path):
    vault = MemoryVault()
    vault.unavailable = True
    manager, _, _ = make_manager(
        tmp_path, clock=lambda: "2026-10-17T12:00:00+03:30", vault=vault
    )

    result = manager.configure(
        "quera",
        "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )

    assert result == {"status": "secure_store_unavailable"}
    assert not list(tmp_path.rglob("*.json"))


def test_credential_rotation_invalidates_sessions_and_old_continuations(tmp_path):
    now = "2026-10-17T12:00:00+03:30"
    manager, vault, _ = make_manager(tmp_path, clock=lambda: now)
    configured = manager.configure(
        "quera",
        "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )
    challenge = manager.observe(configured["connection_id"], {"scope": "classes"})
    vault.put("session:" + configured["connection_id"], {"cookie": "old-session"})

    updated = manager.update_credentials(
        configured["connection_id"],
        {"username": "student@example.test", "password": "new-password"},
        expected_generation=1,
    )
    stale = manager.update_credentials(
        configured["connection_id"],
        {"username": "student@example.test", "password": "stale-password"},
        expected_generation=1,
    )
    continued = manager.continue_operation(
        challenge["continuation_id"], {"kind": "otp", "value": "123456"}
    )

    assert updated == {"status": "ok", "connection_id": configured["connection_id"],
                       "credential_generation": 2}
    assert stale["status"] == "conflict"
    assert vault.get("credentials:{}:2".format(configured["connection_id"]))["password"] == "new-password"
    assert vault.get("session:" + configured["connection_id"]) is None
    assert continued["status"] == "account_mismatch"


def test_rotating_credentials_cannot_rebind_a_connection_to_another_account(tmp_path):
    manager, vault, _ = make_manager(
        tmp_path, clock=lambda: "2026-10-17T12:00:00+03:30"
    )
    configured = manager.configure(
        "quera",
        "https://quera.org",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )

    changed = manager.update_credentials(
        configured["connection_id"],
        {"username": "different@example.test", "password": "another-password"},
        expected_generation=1,
    )

    assert changed["status"] == "account_mismatch"
    assert vault.get("credentials:{}:1".format(configured["connection_id"])) == {
        "username": "student@example.test",
        "password": "not-a-real-password",
    }
    assert vault.get("credentials:{}:2".format(configured["connection_id"])) is None


def test_configure_rejects_origins_that_could_receive_the_platform_password(tmp_path):
    manager, _, _ = make_manager(
        tmp_path, clock=lambda: "2026-10-17T12:00:00+03:30"
    )

    result = manager.configure(
        "quera",
        "https://attacker.example",
        {"username": "student@example.test", "password": "not-a-real-password"},
    )

    assert result == {"status": "invalid_input"}


def test_windows_vault_encrypts_values_at_rest_and_round_trips(tmp_path):
    if __import__("os").name != "nt":
        pytest.skip("Windows DPAPI is only available on Windows")
    vault = WindowsDPAPIVault(tmp_path)
    secret = {"username": "private-user", "password": "private-password"}

    vault.put("credentials:connection-id", secret)

    encrypted_file = next(tmp_path.glob("*.bin"))
    assert b"private-password" not in encrypted_file.read_bytes()
    assert vault.get("credentials:connection-id") == secret
    vault.delete("credentials:connection-id")
    assert vault.get("credentials:connection-id") is None
