"""Application operations for protected platform connections."""

from __future__ import annotations

from .platform_runtime import access_manager


def configure(
    platform: str,
    credentials: dict,
    *,
    origin: str | None = None,
    home=None,
    label: str | None = None,
    adapters=None,
    vault=None,
    manager_factory=None,
) -> dict:
    origins = {"cw": "https://cw.sharif.ir", "quera": "https://quera.org"}
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.configure(platform, origin or origins.get(platform, ""), credentials, label=label)


def view(*, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable", "connections": []}
    return {
        "status": "ok",
        "connections": [
            {key: item[key] for key in ("platform", "label", "origin", "created_at", "state")}
            for item in manager.connections()
        ],
    }


def label_update(connection_id: str, label: str, *, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.update_label(connection_id, label)


def rename(current_label: str, label: str, *, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.update_label_by_name(current_label, label)


def forget_named(label: str, *, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.forget_by_name(label)


def update_named(label: str, credentials: dict, *, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.update_credentials_by_name(label, credentials)


def forget(connection_id: str, *, home=None, adapters=None, vault=None, manager_factory=None) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.forget(connection_id)


def update(
    connection_id: str,
    credentials: dict,
    *,
    expected_generation: int,
    home=None,
    adapters=None,
    vault=None,
    manager_factory=None,
) -> dict:
    manager = (manager_factory or access_manager)(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    return manager.update_credentials(
        connection_id, credentials, expected_generation=expected_generation
    )
