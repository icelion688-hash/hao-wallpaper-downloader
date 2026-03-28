import unittest

from backend.core.upload_record_helper import infer_upload_state, reconcile_wallpaper_upload_state
from backend.models.wallpaper import Wallpaper


class UploadStateTests(unittest.TestCase):
    def test_uploaded_when_remote_url_exists(self):
        status, note = infer_upload_state(
            imgbed_url='https://example.com/file/a.png',
            upload_records=None,
        )
        self.assertEqual(status, 'uploaded')
        self.assertEqual(note, '')

    def test_preview_with_original_only_profile_is_skipped(self):
        status, note = infer_upload_state(
            imgbed_url=None,
            upload_records=None,
            is_original=False,
            current_profile_only_original=True,
        )
        self.assertEqual(status, 'skipped')
        self.assertIn('仅上传原图', note)

    def test_missing_remote_without_explicit_status_is_pending(self):
        status, note = infer_upload_state(
            imgbed_url=None,
            upload_records=None,
            is_original=True,
            current_profile_only_original=True,
        )
        self.assertEqual(status, 'pending')
        self.assertEqual(note, '未上传到图床')

    def test_invalid_upload_records_are_not_treated_as_uploaded(self):
        status, note = infer_upload_state(
            imgbed_url=None,
            upload_records='{"broken":{"remote_path":"bg/pc/demo.webp"}}',
            upload_status='failed',
            upload_note='图床上传失败',
        )
        self.assertEqual(status, 'failed')
        self.assertEqual(note, '图床上传失败')

    def test_reconcile_upload_state_fills_imgbed_url_from_records(self):
        wallpaper = Wallpaper(
            resource_id='demo-1',
            status='done',
            upload_status='failed',
            upload_note='图床上传失败',
            upload_records='{"original_lossless":{"profile_key":"original_lossless","url":"https://img.example.com/file/demo.webp"}}',
            imgbed_url=None,
        )

        result = reconcile_wallpaper_upload_state(wallpaper)

        self.assertTrue(result['changed'])
        self.assertEqual(wallpaper.upload_status, 'uploaded')
        self.assertEqual(wallpaper.imgbed_url, 'https://img.example.com/file/demo.webp')
        self.assertEqual(wallpaper.upload_note, '已同步上传记录')


if __name__ == '__main__':
    unittest.main()
