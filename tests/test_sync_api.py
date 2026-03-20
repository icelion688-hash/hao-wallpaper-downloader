import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api import sync
from backend.models.database import Base, get_db
from backend.models.sync_history import SyncHistory
from backend.models.upload_registry import UploadRegistry


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _MockAsyncClient:
    def __init__(self, *args, **kwargs):
        self.payload = kwargs.pop("payload")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        return _MockResponse(self.payload)


class SyncApiTests(unittest.TestCase):
    def setUp(self):
        sync._SYNC_RATE_LIMIT_BUCKETS.clear()

        engine = create_engine(
            'sqlite://',
            connect_args={'check_same_thread': False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        self.app = FastAPI()
        self.app.include_router(sync.router, prefix='/api/sync')

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(self.app)

    @contextmanager
    def patch_sync_config(self, sync_patch=None):
        base = {
            "sync": {
                "auth_token": "",
                "allowed_sources": [],
                "export_rate_limit_per_minute": 0,
            }
        }
        if sync_patch:
            base["sync"].update(sync_patch)
        with patch('backend.api.sync.load_config', return_value=base):
            yield

    def seed_registry(self):
        db = self.Session()
        try:
            db.add_all([
                UploadRegistry(
                    resource_id='8001',
                    sha256='sha-8001',
                    profile_key='compressed_webp',
                    format_key='profile',
                    url='https://img.example.com/j1.webp',
                ),
                UploadRegistry(
                    resource_id='8002',
                    sha256='sha-8002',
                    profile_key='compressed_webp',
                    format_key='original',
                    url='https://img.example.com/j2.png',
                ),
                UploadRegistry(
                    resource_id='8003',
                    sha256='sha-8003',
                    profile_key='telegram_backup',
                    format_key='profile',
                    url='https://img.example.com/j3.webp',
                ),
            ])
            db.commit()
        finally:
            db.close()

    def test_handshake_rejects_source_outside_allowlist(self):
        with self.patch_sync_config({"allowed_sources": ["192.168.1.10"]}):
            response = self.client.get('/api/sync/handshake')

        self.assertEqual(response.status_code, 403)
        self.assertIn('不在同步白名单内', response.json()['detail'])

    def test_handshake_rate_limit_returns_429(self):
        with self.patch_sync_config({"allowed_sources": ["testclient"], "export_rate_limit_per_minute": 1}):
            first = self.client.get('/api/sync/handshake')
            second = self.client.get('/api/sync/handshake')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)

    def test_export_filters_records_and_writes_history(self):
        self.seed_registry()

        with self.patch_sync_config({"allowed_sources": ["testclient"]}):
            response = self.client.get(
                '/api/sync/export',
                params={'profile_keys': 'compressed_webp', 'format_keys': 'profile'},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['total'], 1)
        self.assertEqual(payload['records'][0]['resource_id'], '8001')

        history = self.client.get('/api/sync/history?limit=5').json()
        self.assertEqual(history['items'][0]['type'], 'export')

    def test_import_endpoint_persists_registry_and_history(self):
        payload = {
            "version": 3,
            "records": [
                {
                    "resource_id": "9001",
                    "sha256": "sha-9001",
                    "profile_key": "compressed_webp",
                    "format_key": "profile",
                    "url": "https://img.example.com/k1.webp",
                }
            ],
        }

        response = self.client.post(
            '/api/sync/import',
            files={'file': ('sync.json', json.dumps(payload, ensure_ascii=False), 'application/json')},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['inserted'], 1)

        db = self.Session()
        try:
            self.assertEqual(db.query(UploadRegistry).count(), 1)
            latest_history = db.query(SyncHistory).order_by(SyncHistory.id.desc()).first()
            self.assertEqual(latest_history.action, 'import')
        finally:
            db.close()

    def test_history_endpoint_returns_latest_items(self):
        db = self.Session()
        try:
            db.add(SyncHistory(action='probe', status='success', summary='远程连接正常'))
            db.add(SyncHistory(action='pull', status='success', summary='迁移完成'))
            db.commit()
        finally:
            db.close()

        response = self.client.get('/api/sync/history?limit=2')

        self.assertEqual(response.status_code, 200)
        items = response.json()['items']
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['type'], 'pull')
        self.assertEqual(items[1]['type'], 'probe')

    def test_probe_endpoint_records_history(self):
        payload = {
            "ok": True,
            "version": 3,
            "server": "hao-wallpaper-downloader",
            "source": "10.0.0.8",
            "stats": {
                "registry_exportable": 12,
                "registry_total": 18,
                "export_allowlist_enabled": True,
                "export_rate_limit_per_minute": 60,
            },
            "warning": None,
        }

        with patch('backend.api.sync.httpx.AsyncClient', lambda *args, **kwargs: _MockAsyncClient(payload=payload)):
            response = self.client.post(
                '/api/sync/probe',
                json={'remote_base_url': 'http://10.0.0.8:8000'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['request_source'], '10.0.0.8')

        db = self.Session()
        try:
            latest_history = db.query(SyncHistory).order_by(SyncHistory.id.desc()).first()
            self.assertEqual(latest_history.action, 'probe')
            self.assertIn('连接正常', latest_history.summary)
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main()
