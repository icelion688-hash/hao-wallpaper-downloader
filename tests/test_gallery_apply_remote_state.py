import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import gallery
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


if __name__ == '__main__':
    unittest.main()
