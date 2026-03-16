"""
config.py - 读取与保存全局配置。
"""

import copy
import os

import yaml

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


def load_config() -> dict:
    cfg = _deep_merge(_default_config(), _read_raw_config())
    _normalize_upload_profiles(cfg)
    return cfg


def save_config(cfg: dict) -> dict:
    merged = _deep_merge(_default_config(), cfg or {})
    _normalize_upload_profiles(merged)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    return merged


def update_config(patch: dict) -> dict:
    current = _read_raw_config()
    merged = _deep_merge(current, patch or {})
    return save_config(merged)


def _read_raw_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _normalize_upload_profiles(cfg: dict) -> None:
    uploads = cfg.setdefault("uploads", {})
    profiles = uploads.get("profiles") or []

    if not profiles:
        legacy = cfg.get("imgbed", {})
        profiles = [
            _deep_merge(_default_upload_profiles()[0], legacy),
            _default_upload_profiles()[1],
        ]
        uploads["profiles"] = profiles

    default_profiles = {item["key"]: item for item in _default_upload_profiles()}
    normalized = []
    for profile in profiles:
        key = profile.get("key")
        base = copy.deepcopy(default_profiles.get(key, _default_upload_profile_template(key)))
        normalized.append(_deep_merge(base, profile))

    uploads["profiles"] = normalized
    uploads.setdefault("task_profile", normalized[0]["key"])

    # 兼容旧字段，始终同步为任务默认图床
    task_profile = next((p for p in normalized if p["key"] == uploads["task_profile"]), normalized[0])
    cfg["imgbed"] = copy.deepcopy(task_profile)


def _default_upload_profile_template(key: str | None = None) -> dict:
    return {
        "key": key or "custom_profile",
        "name": "自定义图床",
        "enabled": False,
        "base_url": "https://imgbed.lacexr.com",
        "api_token": "",
        "channel": "telegram",
        "server_compress": False,
            "image_processing": {
                "enabled": False,
                "telegram_only": False,
                "format": "original",
                "quality": 86,
                "min_quality": 72,
                "threshold_mb": 5,
            "target_mb": 4,
            "disable_above_mb": 10,
        },
    }


def _default_upload_profiles() -> list[dict]:
    return [
        {
            "key": "compressed_webp",
            "name": "壁纸压缩图床",
            "enabled": True,
            "base_url": "https://imgbed.lacexr.com",
            "api_token": "",
            "channel": "telegram",
            "server_compress": True,
            "image_processing": {
                "enabled": True,
                "telegram_only": False,
                "format": "webp",
                "quality": 86,
                "min_quality": 72,
                "threshold_mb": 5,
                "target_mb": 4,
                "disable_above_mb": 10,
            },
        },
        {
            "key": "original_lossless",
            "name": "原图无损图床",
            "enabled": False,
            "base_url": "https://imgbed.lacexr.com",
            "api_token": "",
            "channel": "huggingface",
            "server_compress": False,
            "image_processing": {
                "enabled": False,
                "telegram_only": False,
                "format": "original",
                "quality": 100,
                "min_quality": 100,
                "threshold_mb": 5,
                "target_mb": 4,
                "disable_above_mb": 10,
            },
        },
    ]


def _default_config() -> dict:
    return {
        "proxies": [],
        "use_proxy": False,
        "min_delay": 0.5,
        "max_delay": 2.0,
        "download_root": "downloads",
        "concurrency": 3,
        "free_daily_limit": 10,
        "log_level": "INFO",
        "imgbed": _default_upload_profiles()[0],
        "uploads": {
            "task_profile": "compressed_webp",
            "profiles": _default_upload_profiles(),
        },
    }
