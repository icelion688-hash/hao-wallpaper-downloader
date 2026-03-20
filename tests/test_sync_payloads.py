import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.sync import (
    _build_export_options,
    _build_export_payload,
    _build_duplicate_scan_result,
    _build_preview_result,
    _build_registry_identity,
    _consume_rate_limit,
    _is_source_allowed,
    _is_sync_token_valid,
    _merge_duplicate_group_rows,
    _normalize_import_records,
    _record_sync_history,
    _serialize_sync_history_item,
)
from backend.models.database import Base
from backend.models.sync_history import SyncHistory
from backend.models.upload_registry import UploadRegistry


class SyncPayloadTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False})
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def test_sync_token_validation_allows_empty_config(self):
        with patch('backend.api.sync.load_config', return_value={"sync": {"auth_token": ""}}):
            self.assertTrue(_is_sync_token_valid(None))
            self.assertTrue(_is_sync_token_valid("anything"))

    def test_sync_token_validation_checks_expected_token(self):
        with patch('backend.api.sync.load_config', return_value={"sync": {"auth_token": "secret-123"}}):
            self.assertTrue(_is_sync_token_valid("secret-123"))
            self.assertFalse(_is_sync_token_valid("wrong-token"))

    def test_is_source_allowed_supports_ip_and_cidr(self):
        self.assertTrue(_is_source_allowed('192.168.1.10', ['192.168.1.10']))
        self.assertTrue(_is_source_allowed('10.0.0.8', ['10.0.0.0/24']))
        self.assertFalse(_is_source_allowed('10.0.1.8', ['10.0.0.0/24']))
        self.assertTrue(_is_source_allowed('sync-node', ['sync-node']))

    def test_consume_rate_limit_blocks_after_threshold(self):
        _consume_rate_limit('export-test', '192.168.1.10', 2, now=10)
        _consume_rate_limit('export-test', '192.168.1.10', 2, now=20)
        with self.assertRaises(Exception):
            _consume_rate_limit('export-test', '192.168.1.10', 2, now=30)
        _consume_rate_limit('export-test', '192.168.1.10', 2, now=71)

    def test_record_sync_history_persists_item(self):
        session = self.Session()
        try:
            _record_sync_history(
                session,
                action='pull',
                summary='节点 A 迁移完成',
                remote_base_url='http://10.0.0.8:8000',
                source_server='10.0.0.8:8000',
            )
            session.commit()

            item = session.query(SyncHistory).first()

            self.assertIsNotNone(item)
            self.assertEqual(item.action, 'pull')
            self.assertEqual(item.summary, '节点 A 迁移完成')
        finally:
            session.close()

    def test_serialize_sync_history_item_maps_label(self):
        item = SyncHistory(
            id=3,
            action='probe',
            status='success',
            summary='远程连接正常',
            detail='协议版本 3',
            remote_base_url='http://10.0.0.8:8000',
            source_server='10.0.0.8:8000',
            created_at=datetime.fromisoformat('2026-03-20T12:30:00'),
        )

        payload = _serialize_sync_history_item(item)

        self.assertEqual(payload.type, 'probe')
        self.assertEqual(payload.type_label, '测试')
        self.assertEqual(payload.summary, '远程连接正常')
        self.assertEqual(payload.at, '2026-03-20T12:30:00')

    def test_normalize_import_records_accepts_registry_format(self):
        payload = {
            "version": 3,
            "records": [
                {
                    "resource_id": "1001",
                    "sha256": "sha-1",
                    "md5": "md5-1",
                    "profile_key": "compressed_webp",
                    "format_key": "profile",
                    "profile_name": "压缩图床",
                    "channel": "telegram",
                    "url": "https://img.example.com/a.webp",
                    "uploaded_at": "2026-03-20T10:00:00",
                }
            ],
        }

        records = _normalize_import_records(payload, source_server="server-a")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["profile_key"], "compressed_webp")
        self.assertEqual(records[0]["url"], "https://img.example.com/a.webp")
        self.assertEqual(records[0]["source_server"], "server-a")

    def test_normalize_import_records_converts_legacy_wallpaper_payload(self):
        payload = {
            "version": 2,
            "records": [
                {
                    "resource_id": "2002",
                    "sha256": "sha-2",
                    "md5": "md5-2",
                    "upload_records": (
                        '{"compressed_webp":{"profile_key":"compressed_webp",'
                        '"profile_name":"压缩图床","channel":"telegram",'
                        '"url":"https://img.example.com/b.webp",'
                        '"format_key":"profile","uploaded_at":"2026-03-20T11:00:00"}}'
                    ),
                }
            ],
        }

        records = _normalize_import_records(payload, source_server="server-b")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["resource_id"], "2002")
        self.assertEqual(records[0]["sha256"], "sha-2")
        self.assertEqual(records[0]["profile_key"], "compressed_webp")
        self.assertEqual(records[0]["url"], "https://img.example.com/b.webp")
        self.assertEqual(records[0]["source_server"], "server-b")

    def test_build_preview_result_summarizes_payload(self):
        payload = {
            "version": 3,
            "records": [
                {
                    "resource_id": "3003",
                    "sha256": "sha-3",
                    "profile_key": "compressed_webp",
                    "format_key": "profile",
                    "url": "https://img.example.com/c.webp",
                    "source_server": "node-a",
                },
                {
                    "resource_id": "3004",
                    "md5": "md5-4",
                    "profile_key": "original_lossless",
                    "format_key": "original",
                    "url": "https://img.example.com/d.png",
                    "source_server": "node-b",
                },
            ],
        }

        result = _build_preview_result(payload)

        self.assertEqual(result.version, 3)
        self.assertEqual(result.raw_record_count, 2)
        self.assertEqual(result.normalized_count, 2)
        self.assertEqual(result.profile_keys, ["compressed_webp", "original_lossless"])
        self.assertEqual(result.format_keys, ["original", "profile"])
        self.assertEqual(result.source_servers, ["node-a", "node-b"])
        self.assertEqual(result.with_hash_count, 2)

    def test_build_preview_result_warns_when_no_importable_records(self):
        payload = {
            "version": 3,
            "records": [
                {
                    "resource_id": "4001",
                    "profile_key": "compressed_webp",
                }
            ],
        }

        result = _build_preview_result(payload)

        self.assertEqual(result.raw_record_count, 1)
        self.assertEqual(result.normalized_count, 0)
        self.assertIn("没有识别到可导入的上传记录", result.warning or "")

    def test_build_registry_identity_prefers_sha256(self):
        item = UploadRegistry(
            resource_id='5001',
            sha256='sha-5001',
            md5='md5-5001',
            profile_key='compressed_webp',
            format_key='profile',
            url='https://img.example.com/e.webp',
        )

        identity = _build_registry_identity(item)

        self.assertEqual(identity, ('sha256', 'sha-5001', 'sha256:sha-5001|compressed_webp|profile'))

    def test_duplicate_scan_result_groups_registry_rows(self):
        session = self.Session()
        try:
            session.add_all([
                UploadRegistry(
                    resource_id='6001',
                    sha256='sha-6001',
                    profile_key='compressed_webp',
                    format_key='profile',
                    profile_name='压缩图床',
                    url='https://img.example.com/f1.webp',
                ),
                UploadRegistry(
                    resource_id='6001',
                    sha256='sha-6001',
                    profile_key='compressed_webp',
                    format_key='profile',
                    source_server='node-a',
                    url='https://img.example.com/f1.webp',
                ),
                UploadRegistry(
                    resource_id='6002',
                    md5='md5-6002',
                    profile_key='original_lossless',
                    format_key='original',
                    url='https://img.example.com/f2.png',
                ),
            ])
            session.commit()

            items = session.query(UploadRegistry).order_by(UploadRegistry.id.asc()).all()
            result = _build_duplicate_scan_result(items, limit=10)

            self.assertEqual(result.total_groups, 1)
            self.assertEqual(result.total_duplicate_rows, 1)
            self.assertEqual(result.groups[0].profile_key, 'compressed_webp')
            self.assertEqual(result.groups[0].count, 2)
            self.assertEqual(result.groups[0].duplicate_ids, [2])
        finally:
            session.close()

    def test_build_export_payload_filters_by_profile_and_format(self):
        session = self.Session()
        try:
            session.add_all([
                UploadRegistry(
                    resource_id='6101',
                    sha256='sha-6101',
                    profile_key='compressed_webp',
                    format_key='profile',
                    url='https://img.example.com/h1.webp',
                ),
                UploadRegistry(
                    resource_id='6102',
                    sha256='sha-6102',
                    profile_key='compressed_webp',
                    format_key='original',
                    url='https://img.example.com/h2.png',
                ),
                UploadRegistry(
                    resource_id='6103',
                    sha256='sha-6103',
                    profile_key='telegram_backup',
                    format_key='profile',
                    url='https://img.example.com/h3.webp',
                ),
            ])
            session.commit()

            payload = _build_export_payload(
                session,
                include_all=False,
                profile_keys=['compressed_webp'],
                format_keys=['profile'],
            )

            self.assertEqual(payload['total'], 1)
            self.assertEqual(payload['filters']['profile_keys'], ['compressed_webp'])
            self.assertEqual(payload['filters']['format_keys'], ['profile'])
            self.assertEqual(payload['records'][0]['resource_id'], '6101')
        finally:
            session.close()

    def test_build_export_options_summarizes_profiles_and_formats(self):
        session = self.Session()
        try:
            session.add_all([
                UploadRegistry(
                    resource_id='6201',
                    sha256='sha-6201',
                    profile_key='compressed_webp',
                    format_key='profile',
                    url='https://img.example.com/i1.webp',
                ),
                UploadRegistry(
                    resource_id='6202',
                    sha256='sha-6202',
                    profile_key='compressed_webp',
                    format_key='original',
                    url='https://img.example.com/i2.png',
                ),
                UploadRegistry(
                    resource_id='6203',
                    sha256='sha-6203',
                    profile_key='telegram_backup',
                    format_key='profile',
                    url='https://img.example.com/i3.webp',
                ),
            ])
            session.commit()

            items = session.query(UploadRegistry).order_by(UploadRegistry.id.asc()).all()
            result = _build_export_options(items)

            self.assertEqual(
                [(item.key, item.total) for item in result.profile_keys],
                [('compressed_webp', 2), ('telegram_backup', 1)],
            )
            self.assertEqual(
                [(item.key, item.total) for item in result.format_keys],
                [('original', 1), ('profile', 2)],
            )
        finally:
            session.close()

    def test_merge_duplicate_group_rows_keeps_primary_and_deletes_duplicates(self):
        session = self.Session()
        try:
            session.add_all([
                UploadRegistry(
                    resource_id='7001',
                    sha256='sha-7001',
                    profile_key='compressed_webp',
                    format_key='profile',
                    url='https://img.example.com/g1.webp',
                    uploaded_at=datetime.fromisoformat('2026-03-20T10:00:00'),
                ),
                UploadRegistry(
                    resource_id='7001',
                    sha256='sha-7001',
                    md5='md5-7001',
                    profile_key='compressed_webp',
                    format_key='profile',
                    profile_name='压缩图床',
                    channel='telegram',
                    source_server='node-b',
                    url='https://img.example.com/g1.webp',
                    uploaded_at=datetime.fromisoformat('2026-03-19T10:00:00'),
                ),
            ])
            session.commit()

            rows = session.query(UploadRegistry).order_by(UploadRegistry.id.asc()).all()
            changed, removed_count, has_conflict = _merge_duplicate_group_rows(session, rows)
            session.commit()

            remaining = session.query(UploadRegistry).order_by(UploadRegistry.id.asc()).all()

            self.assertFalse(changed)
            self.assertEqual(removed_count, 1)
            self.assertFalse(has_conflict)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0].id, 2)
            self.assertEqual(remaining[0].md5, 'md5-7001')
            self.assertEqual(remaining[0].profile_name, '压缩图床')
            self.assertEqual(remaining[0].channel, 'telegram')
            self.assertEqual(remaining[0].source_server, 'node-b')
            self.assertEqual(remaining[0].uploaded_at, datetime.fromisoformat('2026-03-19T10:00:00'))
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
