"""Application orchestration for refreshing platform coursework observations."""

from __future__ import annotations

from collections.abc import Callable

_SUPPORTED_PLATFORMS = frozenset({"cw", "quera"})


def refresh(
    platforms: list[str] | None,
    *,
    data,
    adapters,
    home,
    vault,
    connection_ids: list[str] | None,
    connection_labels: list[str] | None,
    context_factory: Callable,
    manager_factory: Callable,
    adapter_factory: Callable,
) -> dict:
    """Refresh requested adapters or protected named connections independently."""
    if adapters is not None:
        platform_adapters = list(adapters.values()) if isinstance(adapters, dict) else list(adapters)
        result = context_factory(data, platform_adapters).refresh(platforms=platforms)
        configured = {
            adapter.connection.get("platform")
            for adapter in platform_adapters
            if isinstance(getattr(adapter, "connection", None), dict)
        }
        return _report_unconfigured(result, platforms, configured)

    manager = manager_factory(home, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable", "targets": []}
    connections = manager.connections()
    if connection_labels is not None:
        if not isinstance(connection_labels, list) or not all(
            isinstance(item, str) for item in connection_labels
        ):
            return {"status": "invalid_input", "targets": []}
        selected = set(connection_labels)
        missing = sorted(selected - {item.get("label") for item in connections})
        if missing:
            return {"status": "not_found", "targets": [], "missing_connections": missing}
        connections = [item for item in connections if item.get("label") in selected]
    if connection_ids is not None:
        if not isinstance(connection_ids, list) or not all(
            isinstance(item, str) for item in connection_ids
        ):
            return {"status": "invalid_input", "targets": []}
        selected_ids = set(connection_ids)
        connections = [item for item in connections if item["id"] in selected_ids]
    if platforms is not None:
        selected_platforms = set(platforms)
        connections = [item for item in connections if item["platform"] in selected_platforms]

    result = context_factory(
        data, [adapter_factory(item, manager) for item in connections]
    ).refresh()
    _mark_interactive_challenges_unavailable(result)
    return _report_unconfigured(result, platforms, {item["platform"] for item in connections})


def continue_operation(
    continuation_id: str,
    response: dict,
    *,
    home,
    adapters,
    vault,
    data,
    manager_factory: Callable,
    refresh_operation: Callable,
) -> dict:
    """Resume a saved challenge and refresh only the connection that resumed."""
    manager = manager_factory(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable"}
    result = manager.continue_operation(continuation_id, response)
    if result.get("status") == "challenge_unavailable":
        return result
    if result.get("status") == "ok" and adapters is None:
        refreshed = refresh_operation(
            data=data,
            home=home,
            vault=vault,
            connection_ids=[result["connection_id"]],
        )
        result["refresh"] = refreshed
        if refreshed.get("status") != "ok":
            result["status"] = "partial"
    return result


def challenges(*, home, adapters, vault, manager_factory: Callable) -> dict:
    """Return pending challenges for the CLI without exposing private state."""
    manager = manager_factory(home, adapters=adapters, vault=vault)
    if manager is None:
        return {"status": "secure_store_unavailable", "challenges": []}
    return {"status": "ok", "challenges": manager.pending_challenges()}


def _mark_interactive_challenges_unavailable(result: dict) -> None:
    actions = result.get("actions", [])
    connection_ids = {
        action.get("connection_id")
        for action in actions
        if (action.get("challenge") or {}).get("kind") == "interactive"
    }
    for target in result.get("targets", []):
        if target.get("connection_id") in connection_ids:
            target["status"] = "challenge_unavailable"
    for action in actions:
        if action.get("connection_id") in connection_ids:
            action["status"] = "challenge_unavailable"
            action["guidance"] = "در مرورگر کوئرا ادامه بده؛ این نشست API احراز نمی‌شود."
    if connection_ids:
        result["status"] = "partial"


def _report_unconfigured(result: dict, requested: list[str] | None, configured: set[str]) -> dict:
    if not isinstance(requested, list):
        return result
    missing = [
        platform for platform in requested
        if platform in _SUPPORTED_PLATFORMS and platform not in configured
    ]
    if missing:
        result.setdefault("targets", []).extend(
            {"platform": platform, "status": "needs_credentials"} for platform in missing
        )
        result["status"] = "partial"
    return result
