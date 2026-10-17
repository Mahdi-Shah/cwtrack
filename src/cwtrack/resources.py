"""A local library of supplementary resources and their course bindings."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import urllib.error
import urllib.request
import uuid
from ipaddress import ip_address
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

_MAX_CAPTURE_BYTES = 25 * 1024 * 1024


class ResourceLibrary:
    """Register resources once and attach them to explicit course/work targets."""

    def __init__(self, paths: dict, *, clock: Callable[[], str], content_reader=None):
        if not isinstance(paths, dict) or not paths.get("data"):
            raise ValueError("ResourceLibrary requires an explicit data path")
        self._data = Path(paths["data"]).expanduser().resolve()
        self._root = self._data / "catalog-v2" / "resource-library"
        self._manifest = self._root / "library.json"
        self._clock = clock
        self._content_reader = content_reader or _read_remote

    def attach(self, spec_or_id, *, to: dict, extent: dict | None = None) -> dict:
        """Register a resource if needed, then bind it to one explicit target."""
        target = self._validate_target(to)
        if extent is not None and not isinstance(extent, dict):
            raise ValueError("resource extent must be a mapping")

        manifest = self._read()
        resources = manifest["resources"]
        bindings = manifest["bindings"]
        if isinstance(spec_or_id, str):
            resource_id = spec_or_id
            if resource_id not in resources:
                raise ValueError("resource was not found")
            resource = resources[resource_id]
        elif isinstance(spec_or_id, dict):
            resource = self._new_resource(spec_or_id)
            resource_id = resource["id"]
            resources[resource_id] = resource
        else:
            raise ValueError("resource must be an ID or a resource specification")

        binding_id = uuid.uuid4().hex
        binding = {
            "id": binding_id,
            "resource_id": resource_id,
            "target": target,
            "extent": extent or {},
            "active": True,
            "revision": 1,
            "created_at": self._clock(),
        }
        bindings[binding_id] = binding
        manifest["revision"] += 1
        self._write(manifest)
        return {"resource_id": resource_id, "binding_id": binding_id}

    def detach(self, binding_id: str, *, expected_revision: int) -> dict:
        """Disable one target binding while retaining resources and captures."""
        manifest = self._read()
        if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
            return {"status": "invalid_input", "revision": manifest["revision"]}
        if manifest["revision"] != expected_revision:
            return {"status": "conflict", "revision": manifest["revision"]}
        binding = manifest["bindings"].get(binding_id)
        if binding is None:
            return {"status": "not_found", "revision": manifest["revision"]}
        if not binding["active"]:
            return {"status": "exists", "revision": manifest["revision"]}
        binding["active"] = False
        binding["revision"] += 1
        manifest["revision"] += 1
        self._write(manifest)
        return {"status": "ok", "revision": manifest["revision"]}

    def update(
        self, resource_id: str, replacement: dict, *, expected_revision: int
    ) -> dict:
        """Move the current resource head while retaining all captured versions."""
        manifest = self._read()
        resource = manifest["resources"].get(resource_id)
        if resource is None:
            return {"status": "not_found", "revision": manifest["revision"]}
        if (
            not isinstance(expected_revision, int)
            or isinstance(expected_revision, bool)
        ):
            return {"status": "invalid_input", "revision": manifest["revision"]}
        if resource["revision"] != expected_revision:
            return {"status": "conflict", "revision": manifest["revision"]}
        if not isinstance(replacement, dict):
            return {"status": "invalid_input", "revision": manifest["revision"]}

        spec = {
            "title": replacement.get("title", resource["title"]),
            "location": replacement.get("location", resource["location"]),
            "provenance": replacement.get("provenance", resource["provenance"]),
        }
        updated = self._new_resource(spec)
        updated.update({
            "id": resource_id,
            "revision": resource["revision"] + 1,
            "created_at": resource["created_at"],
            "updated_at": self._clock(),
        })
        manifest["resources"][resource_id] = updated
        manifest["revision"] += 1
        self._write(manifest)
        return {
            "status": "ok",
            "resource": updated,
            "revision": manifest["revision"],
        }

    def capture(self, resource_id: str, *, extent: dict) -> dict:
        """Copy a local file into an immutable snapshot without recording its use."""
        if not isinstance(extent, dict) or not extent:
            raise ValueError("capture extent must identify the requested material")
        manifest = self._read()
        resource = manifest["resources"].get(resource_id)
        if resource is None:
            raise ValueError("resource was not found")
        bindings = [
            binding for binding in manifest["bindings"].values()
            if binding["resource_id"] == resource_id and binding["active"]
        ]
        if not any(
            not binding["extent"]
            or _extent_is_within(binding["extent"], extent)
            for binding in bindings
        ):
            raise ValueError("capture extent is outside every active binding")
        location = resource["location"]
        kind = location.get("kind")
        if kind == "video":
            return {
                "status": "reference_only",
                "resource_id": resource_id,
                "requested_extent": extent,
                "message": "ویدئو فقط به‌عنوان ارجاع ثبت شد؛ متن یا بخش دریافت‌شده لازم است.",
            }

        capture_id = uuid.uuid4().hex
        capture_root = self._data / "catalog-v2" / "resource-captures" / resource_id
        capture_root.mkdir(parents=True, exist_ok=True)
        temporary = capture_root / ("." + capture_id + ".tmp")
        final = capture_root / capture_id
        artifact_name = "resource.bin"
        acquired_extent = {"kind": "whole_file"}
        try:
            temporary.mkdir()
            if kind == "file":
                source = Path(location["path"])
                if not source.is_file():
                    raise ValueError("resource file is unavailable")
                artifact_name = source.name
                artifact = temporary / artifact_name
                shutil.copyfile(source, artifact)
            elif kind == "folder":
                selected = _selected_folder_files(Path(location["path"]), extent)
                artifact_name = "selected-files.zip"
                artifact = temporary / artifact_name
                total = 0
                with ZipFile(artifact, "w", ZIP_DEFLATED) as archive:
                    for relative, source in selected:
                        total += source.stat().st_size
                        if total > _MAX_CAPTURE_BYTES:
                            raise ValueError("folder capture exceeds the size limit")
                        archive.write(source, arcname=relative)
                acquired_extent = {"files": [relative for relative, _ in selected]}
            elif kind in {"web", "remote_file"}:
                result = self._content_reader(location["url"])
                if not isinstance(result, dict) or not isinstance(result.get("content"), bytes):
                    raise ValueError("remote reader returned no content")
                content = result["content"]
                if len(content) > _MAX_CAPTURE_BYTES:
                    raise ValueError("remote resource exceeds the size limit")
                final_url = result.get("final_url", location["url"])
                artifact_name = _remote_filename(final_url, result.get("content_type", ""))
                artifact = temporary / artifact_name
                artifact.write_bytes(content)
                acquired_extent = {"kind": "whole_resource", "url": final_url}
            else:
                raise ValueError("resource kind cannot be captured")
            digest = hashlib.sha256()
            with artifact.open("rb") as copied:
                for chunk in iter(lambda: copied.read(1024 * 1024), b""):
                    digest.update(chunk)
            os.replace(temporary, final)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

        record = {
            "capture_id": capture_id,
            "resource_id": resource_id,
            "resource_revision": resource["revision"],
            "sha256": digest.hexdigest(),
            "source_version": "sha256:" + digest.hexdigest(),
            "artifact_path": (final / artifact_name).relative_to(self._data).as_posix(),
            "requested_extent": extent,
            "acquired_extent": acquired_extent,
            "status": "captured",
            "captured_at": self._clock(),
        }
        manifest["captures"].append(record)
        manifest["revision"] += 1
        self._write(manifest)
        return {**record, "artifact_path": str(self._data / record["artifact_path"])}

    def resolve_uses(self, uses: list[dict]) -> list[dict]:
        """Resolve reported use to captured bytes and reject invented snapshots."""
        if not isinstance(uses, list):
            raise ValueError("resource uses must be a list")
        manifest = self._read()
        captures = {item["capture_id"]: item for item in manifest["captures"]}
        resolved = []
        for use in uses:
            if not isinstance(use, dict):
                raise ValueError("resource use must be a mapping")
            capture_id = use.get("capture_id")
            capture = captures.get(capture_id)
            if capture is None or capture.get("status") != "captured":
                raise ValueError("resource capture was not found")
            used_extent = use.get("used_extent")
            if not isinstance(used_extent, dict) or not used_extent:
                raise ValueError("used resource extent is required")
            if not _extent_is_within(capture.get("requested_extent", {}), used_extent):
                raise ValueError("used extent is outside the captured request")
            part_ids = use.get("part_ids")
            section_ids = use.get("section_ids")
            requirement_ids = use.get("requirement_ids")
            purpose = use.get("purpose")
            if not _nonempty_strings(part_ids):
                raise ValueError("used resource parts are required")
            captured_files = capture.get("acquired_extent", {}).get("files")
            if captured_files is not None and not set(part_ids).issubset(captured_files):
                raise ValueError("used resource parts exceed captured folder members")
            if not _nonempty_strings(section_ids) or not _nonempty_strings(requirement_ids):
                raise ValueError("resource use must reference answer sections and requirements")
            if not isinstance(purpose, str) or not purpose.strip():
                raise ValueError("resource use purpose is required")

            artifact = (self._data / capture["artifact_path"]).resolve()
            if not artifact.is_relative_to(self._data) or not artifact.is_file():
                raise ValueError("captured resource artifact is unavailable")
            digest = _sha256_file(artifact)
            if digest != capture["sha256"]:
                raise ValueError("captured resource artifact changed")
            resolved.append({
                "capture_id": capture_id,
                "resource_id": capture["resource_id"],
                "sha256": digest,
                "part_ids": list(part_ids),
                "used_extent": dict(used_extent),
                "section_ids": list(section_ids),
                "requirement_ids": list(requirement_ids),
                "purpose": purpose.strip(),
            })
        return resolved

    def view(self, *, target: dict | None = None) -> dict:
        """Read registered sources and active bindings without claiming use."""
        manifest = self._read()
        normalized_target = self._validate_target(target) if target is not None else None
        bindings = [
            binding for binding in manifest["bindings"].values()
            if binding["active"]
            and (normalized_target is None or binding["target"] == normalized_target)
        ]
        resources = [
            manifest["resources"][binding["resource_id"]]
            for binding in bindings
        ]
        resource_ids = {resource["id"] for resource in resources}
        captures = [
            capture for capture in manifest["captures"]
            if capture["resource_id"] in resource_ids
        ]
        return {
            "revision": manifest["revision"],
            "resources": resources,
            "bindings": bindings,
            "captures": captures,
        }

    def _read(self) -> dict:
        if not self._manifest.is_file():
            return {
                "schema_version": 1,
                "revision": 0,
                "resources": {},
                "bindings": {},
                "captures": [],
            }
        manifest = json.loads(self._manifest.read_text(encoding="utf-8"))
        if not all(key in manifest for key in ("revision", "resources", "bindings")):
            raise ValueError("resource library manifest is invalid")
        manifest.setdefault("captures", [])
        return manifest

    def _write(self, manifest: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        temporary = self._manifest.with_name(".library.{}.tmp".format(uuid.uuid4().hex))
        try:
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self._manifest)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _new_resource(self, spec: dict) -> dict:
        title = spec.get("title")
        location = spec.get("location")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("resource title is required")
        if not isinstance(location, dict) or not isinstance(location.get("kind"), str):
            raise ValueError("resource location is required")
        normalized_location = dict(location)
        kind = location["kind"]
        if kind in {"file", "folder"}:
            raw_path = location.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                raise ValueError("local resource path is required")
            path = Path(raw_path).expanduser().resolve()
            if kind == "file" and not path.is_file():
                raise ValueError("resource file was not found")
            if kind == "folder" and not path.is_dir():
                raise ValueError("resource folder was not found")
            normalized_location["path"] = str(path)
        elif kind in {"web", "remote_file", "video"}:
            url = location.get("url")
            parsed = urlparse(url) if isinstance(url, str) else None
            if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("resource URL must use http or https")
        else:
            raise ValueError("unsupported resource location kind")

        return {
            "id": uuid.uuid4().hex,
            "title": title.strip(),
            "location": normalized_location,
            "provenance": spec.get("provenance", "student"),
            "revision": 1,
            "created_at": self._clock(),
        }

    @staticmethod
    def _validate_target(target: dict) -> dict:
        if not isinstance(target, dict) or len(target) != 1:
            raise ValueError("target must identify one offering or task")
        if isinstance(target.get("offering_id"), str) and target["offering_id"]:
            return {"offering_id": target["offering_id"]}
        if isinstance(target.get("task_ref"), dict) and target["task_ref"]:
            return {"task_ref": dict(target["task_ref"])}
        raise ValueError("target must identify one offering or task")


def _nonempty_strings(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extent_is_within(requested: dict, used: dict) -> bool:
    if not requested or not used or not set(used).issubset(requested):
        return False
    for kind, value in used.items():
        allowed = requested[kind]
        if kind == "files" and isinstance(allowed, list) and isinstance(value, list):
            if not all(isinstance(item, str) for item in allowed + value):
                return False
            if not set(value).issubset(allowed):
                return False
        elif kind == "pages" and isinstance(allowed, str) and isinstance(value, str):
            allowed_range = _page_range(allowed)
            used_range = _page_range(value)
            if allowed_range is None or used_range is None:
                return False
            if used_range[0] < allowed_range[0] or used_range[1] > allowed_range[1]:
                return False
        elif allowed != value:
            return False
    return True


def _page_range(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", value)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2) or start)
    if end < start:
        return None
    return start, end


def _selected_folder_files(root: Path, extent: dict) -> list[tuple[str, Path]]:
    if not isinstance(extent.get("files"), list) or not extent["files"]:
        raise ValueError("folder capture requires an explicit files list")
    base = root.expanduser().resolve()
    if not base.is_dir():
        raise ValueError("resource folder is unavailable")
    selected = []
    seen = set()
    for relative in extent["files"]:
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("folder members must be relative paths")
        candidate_path = Path(relative)
        if candidate_path.is_absolute() or ".." in candidate_path.parts:
            raise ValueError("folder member escaped the resource folder")
        candidate = base / candidate_path
        current = base
        for part in candidate_path.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("selected folder member is unavailable")
        source = candidate.resolve()
        try:
            normalized = source.relative_to(base).as_posix()
        except ValueError as exc:
            raise ValueError("folder member escaped the resource folder") from exc
        if not source.is_file():
            raise ValueError("selected folder member is unavailable")
        if normalized in seen:
            raise ValueError("folder capture contains duplicate members")
        seen.add(normalized)
        selected.append((normalized, source))
    return selected


def _remote_filename(url: str, content_type: str) -> str:
    name = Path(urlsplit(url).path).name
    if not name or name in {".", ".."}:
        name = "resource"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "resource"
    if not Path(name).suffix:
        media_type = content_type.split(";", 1)[0].strip().lower()
        suffix = {
            "text/html": ".html",
            "text/plain": ".txt",
            "application/pdf": ".pdf",
        }.get(media_type, ".bin")
        name += suffix
    return name


def _validate_public_url(url: str) -> None:
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("resource URL must be a public http or https address")
    try:
        addresses = {ip_address(item[4][0]) for item in socket.getaddrinfo(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )}
    except (OSError, ValueError) as exc:
        raise ValueError("resource host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("resource URL resolved to a non-public address")


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        absolute = urljoin(request.full_url, new_url)
        _validate_public_url(absolute)
        return super().redirect_request(request, response, code, message, headers, absolute)


def _read_remote(url: str) -> dict:
    _validate_public_url(url)
    opener = urllib.request.build_opener(_PublicRedirectHandler())
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "cwtrack/0.1 coursework resource reader",
            "Accept": "text/html,text/plain,application/pdf,application/octet-stream;q=0.8",
        },
    )
    try:
        response = opener.open(request, timeout=20)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("remote resource could not be fetched") from exc
    with response:
        final_url = response.geturl()
        _validate_public_url(final_url)
        content = response.read(_MAX_CAPTURE_BYTES + 1)
        if len(content) > _MAX_CAPTURE_BYTES:
            raise ValueError("remote resource exceeds the size limit")
        return {
            "content": content,
            "content_type": response.headers.get("Content-Type", ""),
            "final_url": final_url,
        }
