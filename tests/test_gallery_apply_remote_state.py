import asyncio
import os
import shutil
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import gallery
from backend.core.downloader import DOWNLOAD_ROOT
from backend.core.upload_record_helper import build_remote_file_url, build_upload_record, dump_upload_records, parse_upload_records
from backend.models.database import Base, get_db
from backend.models.upload_registry import UploadRegistry  # noqa: F401
from backend.models.wallpaper import Wallpaper


class GalleryApplyRemoteStateTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        self.app = FastAPI()
        self.app.include_router(gallery.router, prefix='/api/gallery')

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)
        self.test_download_dir = os.path.join(DOWNLOAD_ROOT, "test_gallery_apply_remote_state")
        os.makedirs(self.test_download_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_download_dir, ignore_errors=True)

    def seed_wallpaper(self, *, tags='旧标签'):
        db = self.Session()
        try:
            old_path = 'bg/pc/1774008002575_demo.webp'
            old_url = build_remote_file_url('https://img.example.com', old_path)
            record = build_upload_record(
                profile_key='compressed_webp',
                profile_name='压缩图床',
                channel='telegram',
                url=old_url,
                remote_path=old_path,
                remote_tags=['静态图', '横图', '风景'],
            )
            wallpaper = Wallpaper(
                resource_id='1774008002575',
                title='测试壁纸',
                local_path='wallpaper/1774008002575_demo.webp',
                width=1920,
                height=1080,
                wallpaper_type='static',
                category='动漫｜二次元',
                color_theme='灰/白',
                tags=tags,
                status='done',
                imgbed_url=old_url,
                upload_records=dump_upload_records({'compressed_webp': record}),
            )
            db.add(wallpaper)
            db.commit()
            db.refresh(wallpaper)
            return wallpaper.id
        finally:
            db.close()

    def seed_broken_upload_wallpaper(self):
        db = self.Session()
        try:
            wallpaper = Wallpaper(
                resource_id='1774008002999',
                title='缺失链接的上传记录',
                local_path='wallpaper/1774008002999_demo.webp',
                width=1920,
                height=1080,
                wallpaper_type='static',
                category='动漫｜二次元',
                status='done',
                upload_status='uploaded',
                upload_note='已上传',
                upload_records='{"broken":{"remote_path":"wallpaper/demo.webp"}}',
                imgbed_url=None,
            )
            db.add(wallpaper)
            db.commit()
            db.refresh(wallpaper)
            return wallpaper.id
        finally:
            db.close()

    def seed_remote_missing_wallpaper(self):
        db = self.Session()
        try:
            rel_path = "test_gallery_apply_remote_state/1774008003888_demo.png"
            abs_path = os.path.join(DOWNLOAD_ROOT, rel_path)
            with open(abs_path, "wb") as f:
                f.write(b"fake-image")

            old_path = "wallpaper/static/横图/动漫_二次元/1774008003888_demo.png"
            old_url = build_remote_file_url("https://img.example.com", old_path)
            record = build_upload_record(
                profile_key="compressed_webp",
                profile_name="压缩图床",
                channel="telegram",
                url=old_url,
                remote_path=old_path,
                remote_tags=["静态图", "横图", "动漫_二次元"],
            )
            wallpaper = Wallpaper(
                resource_id="1774008003888",
                title="图床缺失待重传",
                local_path=rel_path,
                width=1920,
                height=1080,
                wallpaper_type="static",
                category="动漫｜二次元",
                color_theme="灰/白",
                tags="二次元",
                is_original=True,
                status="done",
                imgbed_url=old_url,
                upload_records=dump_upload_records({"compressed_webp": record}),
                upload_status="uploaded",
                upload_note="图床上传成功",
            )
            db.add(wallpaper)
            db.commit()
            db.refresh(wallpaper)
            return wallpaper.id
        finally:
            db.close()

    def test_apply_remote_state_updates_record_and_local_tags(self):
        wallpaper_id = self.seed_wallpaper()
        new_path = 'wallpaper/static/横图/动漫_二次元/1774008002575_demo.webp'

        with patch(
            'backend.api.gallery.list_upload_profiles',
            return_value=[{'key': 'compressed_webp', 'base_url': 'https://img.example.com'}],
        ):
            response = self.client.post(
                '/api/gallery/apply-remote-state',
                json={
                    'profile_key': 'compressed_webp',
                    'sync_local_tags': True,
                    'items': [
                        {
                            'path': new_path,
                            'source_path': 'bg/pc/1774008002575_demo.webp',
                            'tags': ['静态图', '横图', '动漫_二次元', '灰_白', '二次元', '少女'],
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['updated_count'], 1)
        self.assertEqual(payload['local_tags_updated_count'], 1)

        db = self.Session()
        try:
            wallpaper = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
            self.assertEqual(wallpaper.tags, '二次元, 少女')
            self.assertEqual(wallpaper.imgbed_url, build_remote_file_url('https://img.example.com', new_path))
            record = parse_upload_records(wallpaper.upload_records)['compressed_webp']
            self.assertEqual(record['remote_path'], new_path)
            self.assertEqual(
                record['remote_tags'],
                ['静态图', '横图', '动漫_二次元', '灰_白', '二次元', '少女'],
            )
        finally:
            db.close()

    def test_apply_remote_state_can_skip_local_tag_update(self):
        wallpaper_id = self.seed_wallpaper(tags='保留标签')
        new_path = 'wallpaper/static/横图/动漫_二次元/1774008002575_demo.webp'

        with patch(
            'backend.api.gallery.list_upload_profiles',
            return_value=[{'key': 'compressed_webp', 'base_url': 'https://img.example.com'}],
        ):
            response = self.client.post(
                '/api/gallery/apply-remote-state',
                json={
                    'profile_key': 'compressed_webp',
                    'sync_local_tags': False,
                    'items': [
                        {
                            'path': new_path,
                            'source_path': 'bg/pc/1774008002575_demo.webp',
                            'tags': [],
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['updated_count'], 1)
        self.assertEqual(payload['local_tags_updated_count'], 0)

        db = self.Session()
        try:
            wallpaper = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
            self.assertEqual(wallpaper.tags, '保留标签')
            record = parse_upload_records(wallpaper.upload_records)['compressed_webp']
            self.assertEqual(record['remote_path'], new_path)
            self.assertEqual(record['remote_tags'], ['静态图', '横图', '风景'])
        finally:
            db.close()

    def test_gallery_uploaded_filter_ignores_invalid_upload_records(self):
        self.seed_wallpaper()
        self.seed_broken_upload_wallpaper()

        with patch(
            'backend.api.gallery.get_upload_settings',
            return_value={'task_profile': '', 'profiles': []},
        ):
            response = self.client.get('/api/gallery', params={'page': 1, 'page_size': 10, 'upload_state': 'uploaded'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 1)

    def test_reconcile_upload_state_repairs_broken_uploaded_flag(self):
        wallpaper_id = self.seed_broken_upload_wallpaper()

        with patch(
            'backend.api.gallery.get_upload_settings',
            return_value={'task_profile': '', 'profiles': []},
        ), patch(
            'backend.api.gallery.get_upload_profile',
            return_value=None,
        ):
            response = self.client.post('/api/gallery/upload-state/reconcile')

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['changed_count'], 1)
        self.assertEqual(payload['status_fixed'], 1)

        db = self.Session()
        try:
            wallpaper = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
            self.assertEqual(wallpaper.upload_status, 'pending')
            self.assertEqual(wallpaper.upload_note, '未上传到图床')
        finally:
            db.close()

    def test_remote_missing_reupload_reuploads_missing_remote_file(self):
        wallpaper_id = self.seed_remote_missing_wallpaper()

        class _FakeUploader:
            base_url = "https://img.example.com"

            async def list_files(self, **kwargs):
                return {"files": []}

            async def aclose(self):
                return None

            def check_upload_eligibility(self, width, height, is_original):
                return True, ""

            async def upload(self, *args, **kwargs):
                return build_remote_file_url(
                    "https://img.example.com",
                    "wallpaper/static/横图/动漫_二次元/1774008003888_demo_retry.png",
                )

            async def set_remote_tags(self, path, tags, action="set"):
                return {"success": True}

        profile = {
            "key": "compressed_webp",
            "name": "压缩图床",
            "base_url": "https://img.example.com",
            "channel": "telegram",
            "enabled": True,
            "api_token": "token",
            "upload_filter": {},
        }

        with patch(
            "backend.api.gallery.get_upload_settings",
            return_value={"task_profile": "compressed_webp", "profiles": [profile]},
        ), patch(
            "backend.api.gallery.get_upload_profile",
            return_value=profile,
        ), patch(
            "backend.api.gallery.list_upload_profiles",
            return_value=[profile],
        ), patch(
            "backend.api.gallery.build_uploader_by_key",
            return_value=_FakeUploader(),
        ):
            db = self.Session()
            try:
                result = asyncio.run(gallery.reupload_remote_missing_for_task_profile(db))
            finally:
                db.close()

        self.assertTrue(result["success"])
        self.assertEqual(result["prepared_count"], 1)
        self.assertEqual(result["upload_result"]["success_count"], 1)

        db = self.Session()
        try:
            wallpaper = db.query(Wallpaper).filter(Wallpaper.id == wallpaper_id).first()
            self.assertEqual(wallpaper.upload_status, "uploaded")
            self.assertIn("retry", wallpaper.imgbed_url)
            record = parse_upload_records(wallpaper.upload_records)["compressed_webp"]
            self.assertIn("retry", record["url"])
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
