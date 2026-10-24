"""Runtime factories shared by access and study application services."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import access
from .paths import STATE_DIR, find_data_dir
from .platforms import CWAdapter, QueraAdapter
from .study import Study


def study_context(data, adapters=None) -> Study:
    data_dir = find_data_dir(str(data) if data else "")
    return Study(
        {"data": data_dir},
        platforms=adapters or [],
        protected_state=None,
        content_reader=None,
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def platform_adapters(home: Path) -> dict:
    """Create supported live adapters with their local challenge/download roots."""
    def clock():
        return datetime.now().astimezone().isoformat(timespec="seconds")

    return {
        "cw": lambda connection: CWAdapter(
            connection, challenge_root=home / "access-challenges", clock=clock
        ),
        "quera": lambda connection: QueraAdapter(
            connection, clock=clock, download_root=home / "platform-downloads"
        ),
    }


class AccessBackedPlatform:
    """Expose protected account observations through Study's adapter contract."""

    def __init__(self, connection: dict, manager: access.AccessManager):
        self.connection = connection
        self._manager = manager

    def observe(self, request: dict, context: dict) -> dict:
        result = self._manager.observe(self.connection["id"], request)
        if result.get("status") == "ok":
            return result.get("receipt", {})
        observation = {
            "status": result.get("status", "unavailable"),
            "scope": request.get("scope"),
            "coverage": "incomplete",
            "nodes": [],
        }
        for key in ("continuation_id", "challenge", "failure_kind"):
            if key in result:
                observation[key] = result[key]
        return observation


def access_manager(
    home=None,
    *,
    adapters=None,
    vault=None,
    adapter_factory=None,
) -> access.AccessManager | None:
    home_dir = Path(home) if home is not None else STATE_DIR
    protected = vault if vault is not None else access.default_vault(home_dir)
    if protected is None:
        return None
    return access.AccessManager(
        {"home": home_dir},
        adapters=(
            adapters if adapters is not None
            else (adapter_factory(home_dir) if adapter_factory else platform_adapters(home_dir))
        ),
        vault=protected,
        clock=lambda: datetime.now().astimezone().isoformat(timespec="seconds"),
    )
