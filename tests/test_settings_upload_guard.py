import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import settings


class _FakeGuard:
    def __init__(self):
        self.apply_settings = AsyncMock()


class SettingsUploadGuardTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(settings.router, prefix="/api/settings")
        self.app.state.upload_guard = _FakeGuard()
        self.client = TestClient(self.app)

    def test_save_upload_settings_updates_running_upload_guard(self):
        payload = {
            "task_profile": "compressed_webp",
            "gallery_default_format": "profile",
            "upload_guard": {
                "enabled": True,
                "interval_minutes": 45,
                "initial_delay_minutes": 5,
            },
            "profiles": [
                {
                    "key": "compressed_webp",
                    "name": "压缩图床",
                    "enabled": True,
                    "base_url": "https://img.example.com",
                    "api_token": "token",
                    "channel": "telegram",
                    "channel_name": "",
                    "auto_retry": True,
                    "upload_name_type": "default",
                    "sync_remote_tags": True,
                    "server_compress": True,
                    "folder_landscape": "bg/pc",
                    "folder_portrait": "bg/mb",
                    "folder_dynamic": "bg/dynamic",
                    "folder_pattern": "",
                    "upload_filter": {
                        "min_width": None,
                        "min_height": None,
                        "only_original": False,
                    },
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
                }
            ],
        }

        with patch("backend.api.settings.update_config", return_value={"uploads": payload}), patch(
            "backend.api.settings.build_task_uploader",
            return_value=None,
        ):
            response = self.client.put("/api/settings/uploads", json=payload)

        self.assertEqual(response.status_code, 200)
        self.app.state.upload_guard.apply_settings.assert_awaited_once_with(
            enabled=True,
            interval_seconds=45 * 60,
            initial_delay_seconds=5 * 60,
        )


if __name__ == "__main__":
    unittest.main()
