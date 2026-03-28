import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import stats
from backend.core.upload_record_helper import build_remote_file_url, build_upload_record, dump_upload_records
from backend.models.database import Base, get_db
from backend.models.wallpaper import Wallpaper


class _FakeUploader:
    def __init__(self, files):
        self._files = files

    async def list_files(self, **kwargs):
        return {"files": self._files}

    async def aclose(self):
        return None


class StatsUploadCompareTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        self.app = FastAPI()
        self.app.include_router(stats.router, prefix="/api/stats")

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

    def seed_uploaded_wallpaper(self):
        db = self.Session()
        try:
            remote_path = "wallpaper/static/横图/动漫_二次元/1774008002575_demo.webp"
            remote_url = build_remote_file_url("https://img.example.com", remote_path)
            record = build_upload_record(
                profile_key="compressed_webp",
                profile_name="压缩图床",
                channel="telegram",
                url=remote_url,
                remote_path=remote_path,
                remote_tags=["静态图", "横图", "动漫_二次元"],
            )
            wallpaper = Wallpaper(
                resource_id="1774008002575",
                title="测试壁纸",
                local_path="wallpaper/1774008002575_demo.webp",
                width=1920,
                height=1080,
                wallpaper_type="static",
                category="动漫｜二次元",
                status="done",
                imgbed_url=remote_url,
                upload_records=dump_upload_records({"compressed_webp": record}),
                upload_status="uploaded",
                upload_note="上传成功",
            )
            db.add(wallpaper)
            db.commit()
        finally:
            db.close()

    def _patch_task_profile(self):
        profile = {
            "key": "compressed_webp",
            "name": "压缩图床",
            "base_url": "https://img.example.com",
            "enabled": True,
            "api_token": "token",
            "upload_filter": {},
        }
        return patch.multiple(
            "backend.api.gallery",
            get_upload_settings=lambda: {"task_profile": "compressed_webp", "profiles": [profile]},
            get_upload_profile=lambda key: profile if key == "compressed_webp" else None,
            list_upload_profiles=lambda: [profile],
        ), patch.multiple(
            "backend.api.stats",
            get_upload_settings=lambda: {"task_profile": "compressed_webp", "profiles": [profile]},
            get_upload_profile=lambda key: profile if key == "compressed_webp" else None,
            is_upload_profile_available=lambda key: key == "compressed_webp",
        )

    def test_compare_remote_coverage_returns_remote_audit(self):
        self.seed_uploaded_wallpaper()
        gallery_patch, stats_patch = self._patch_task_profile()
        fake_uploader = _FakeUploader(
            [{"name": "wallpaper/static/横图/动漫_二次元/1774008002575_demo.webp", "tags": ["静态图"]}]
        )
        with gallery_patch, stats_patch, patch(
            "backend.api.gallery.build_uploader_by_key",
            return_value=fake_uploader,
        ):
            response = self.client.post("/api/stats/upload-coverage/compare-remote")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["audit"]["total_remote"], 1)
        self.assertEqual(payload["audit"]["problem_count"], 0)
        self.assertEqual(payload["coverage"]["historical_uploaded_count"], 1)

    def test_guard_status_defaults_to_disabled_without_runtime_guard(self):
        response = self.client.get("/api/stats/upload-coverage/guard-status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["last_status"], "disabled")


if __name__ == "__main__":
    unittest.main()
