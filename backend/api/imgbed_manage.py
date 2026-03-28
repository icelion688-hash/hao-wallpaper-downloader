from __future__ import annotations

import os
import re
from collections import defaultdict

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.upload_profiles import build_uploader_by_key, get_upload_profile

router = APIRouter()
_REMOTE_DUPLICATE_PREFIX_RE = re.compile(r"^\d+_+")


def _build_profile_uploader(profile_key: str):
    profile = get_upload_profile(profile_key)
    if not profile:
        raise HTTPException(404, f"上传配置不存在: {profile_key}")

    uploader = build_uploader_by_key(profile_key)
    if not uploader:
        raise HTTPException(400, f"上传配置不可用或未启用: {profile_key}")
    return uploader


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, httpx.HTTPStatusError):
        detail = exc.response.text[:500] or str(exc)
        return HTTPException(exc.response.status_code, detail)
    if isinstance(exc, httpx.ConnectError):
        detail = str(exc).strip() or "无法连接图床管理接口，请检查图床地址、网络连通性或 TLS/IPv6 兼容性。"
        return HTTPException(502, detail)
    detail = str(exc).strip() or exc.__class__.__name__
    return HTTPException(502, detail)


class RemoteMoveRequest(BaseModel):
    path: str = Field(..., min_length=1)
    dist: str = ""
    folder: bool = False


class RemoteTagRequest(BaseModel):
    path: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    action: str = "set"


class RemoteBatchTagRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    action: str = "set"


class RemoteDuplicateRequest(BaseModel):
    dir: str = ""


def _normalize_remote_duplicate_name(path: str, metadata: dict | None = None) -> str:
    raw_name = str((metadata or {}).get("FileName") or os.path.basename(str(path or "").strip()) or "").strip()
    if not raw_name:
        return ""
    return _REMOTE_DUPLICATE_PREFIX_RE.sub("", raw_name)


def _build_remote_duplicate_groups(files: list[dict] | None) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("name") or "").strip().strip("/")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        normalized_name = _normalize_remote_duplicate_name(path, metadata)
        if not path or not normalized_name:
            continue
        size_bytes = int(metadata.get("FileSizeBytes") or 0)
        width = int(metadata.get("Width") or 0)
        height = int(metadata.get("Height") or 0)
        file_type = str(metadata.get("FileType") or "").strip().lower()
        key = (normalized_name.lower(), size_bytes, width, height, file_type)
        groups[key].append(
            {
                "path": path,
                "normalized_name": normalized_name,
                "size_bytes": size_bytes,
                "width": width,
                "height": height,
                "file_type": file_type,
                "timestamp": int(metadata.get("TimeStamp") or 0),
                "metadata": metadata,
            }
        )

    results = []
    for items in groups.values():
        if len(items) <= 1:
            continue
        ordered = sorted(items, key=lambda item: (item["timestamp"], item["path"]), reverse=True)
        primary = ordered[0]
        duplicates = ordered[1:]
        results.append(
            {
                "identity": {
                    "normalized_name": primary["normalized_name"],
                    "size_bytes": primary["size_bytes"],
                    "width": primary["width"],
                    "height": primary["height"],
                    "file_type": primary["file_type"],
                },
                "primary": primary,
                "duplicates": duplicates,
            }
        )
    return sorted(
        results,
        key=lambda item: (-len(item["duplicates"]), item["identity"]["normalized_name"]),
    )


@router.get("/{profile_key}/channels")
async def list_channels(profile_key: str):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.list_channels()
        return {"success": True, "profile_key": profile_key, "channels": data}
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.get("/{profile_key}/capabilities")
async def probe_remote_capabilities(profile_key: str):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.probe_capabilities()
        return {"success": True, "profile_key": profile_key, "data": data}
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.get("/{profile_key}/list")
async def list_remote_files(
    profile_key: str,
    start: int = Query(0, ge=0),
    count: int = Query(50, ge=-1, le=500),
    recursive: bool = False,
    dir: str = "",
    search: str = "",
    include_tags: str = Query("", alias="includeTags"),
    exclude_tags: str = Query("", alias="excludeTags"),
    channel: str = "",
    list_type: str = Query("", alias="listType"),
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.list_files(
            start=start,
            count=count,
            recursive=recursive,
            directory=dir,
            search=search,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            channel=channel,
            list_type=list_type,
        )
        return {"success": True, "profile_key": profile_key, "data": data}
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.get("/{profile_key}/index-info")
async def get_remote_index_info(
    profile_key: str,
    dir: str = "",
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.get_index_info(directory=dir)
        return {"success": True, "profile_key": profile_key, "data": data}
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/rebuild-index")
async def rebuild_remote_index(
    profile_key: str,
    dir: str = "",
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.rebuild_index(directory=dir)
        return {"success": True, "profile_key": profile_key, "data": data}
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.delete("/{profile_key}/delete")
async def delete_remote_path(
    profile_key: str,
    path: str = Query(..., min_length=1),
    folder: bool = False,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.delete_remote_path(path, folder=folder)
        return {
            "success": True,
            "profile_key": profile_key,
            "path": path.strip("/"),
            "folder": folder,
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/move")
async def move_remote_path(
    profile_key: str,
    body: RemoteMoveRequest,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.move_remote_path(body.path, dist=body.dist, folder=body.folder)
        return {
            "success": True,
            "profile_key": profile_key,
            "path": body.path.strip("/"),
            "dist": body.dist.strip("/"),
            "folder": body.folder,
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.get("/{profile_key}/tags")
async def get_remote_tags(
    profile_key: str,
    path: str = Query(..., min_length=1),
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.get_remote_tags(path)
        return {
            "success": True,
            "profile_key": profile_key,
            "path": path.strip("/"),
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/tags")
async def set_remote_tags(
    profile_key: str,
    body: RemoteTagRequest,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.set_remote_tags(body.path, body.tags, action=body.action)
        return {
            "success": True,
            "profile_key": profile_key,
            "path": body.path.strip("/"),
            "action": body.action,
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/tags/batch")
async def set_remote_tags_batch(
    profile_key: str,
    body: RemoteBatchTagRequest,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        paths = [str(item).strip("/") for item in body.paths if str(item).strip("/")]
        if not paths:
            raise HTTPException(400, "paths 不能为空")
        data = await uploader.set_remote_tags_batch(paths, body.tags, action=body.action)
        return {
            "success": True,
            "profile_key": profile_key,
            "count": len(paths),
            "action": body.action,
            "data": data,
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/duplicates/scan")
async def scan_remote_duplicates(
    profile_key: str,
    body: RemoteDuplicateRequest,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.list_files(
            directory=str(body.dir or "").strip("/"),
            recursive=True,
            count=-1,
        )
        files = data.get("files") if isinstance(data, dict) else []
        groups = _build_remote_duplicate_groups(files)
        total_duplicates = sum(len(group["duplicates"]) for group in groups)
        return {
            "success": True,
            "profile_key": profile_key,
            "dir": str(body.dir or "").strip("/"),
            "total_groups": len(groups),
            "total_duplicates": total_duplicates,
            "groups": groups[:100],
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()


@router.post("/{profile_key}/duplicates/clean")
async def clean_remote_duplicates(
    profile_key: str,
    body: RemoteDuplicateRequest,
):
    uploader = _build_profile_uploader(profile_key)
    try:
        data = await uploader.list_files(
            directory=str(body.dir or "").strip("/"),
            recursive=True,
            count=-1,
        )
        files = data.get("files") if isinstance(data, dict) else []
        groups = _build_remote_duplicate_groups(files)
        deleted_paths = []
        failed_items = []

        for group in groups:
            for item in group["duplicates"]:
                path = str(item.get("path") or "").strip("/")
                if not path:
                    continue
                try:
                    await uploader.delete_remote_path(path, folder=False)
                    deleted_paths.append(path)
                except Exception as exc:  # noqa: BLE001
                    failed_items.append({"path": path, "reason": str(exc)})

        return {
            "success": not failed_items,
            "profile_key": profile_key,
            "dir": str(body.dir or "").strip("/"),
            "scanned_groups": len(groups),
            "deleted_count": len(deleted_paths),
            "failed_count": len(failed_items),
            "deleted_paths": deleted_paths[:200],
            "failed_items": failed_items[:100],
        }
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc)
    finally:
        await uploader.aclose()
