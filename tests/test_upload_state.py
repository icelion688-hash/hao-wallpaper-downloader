import unittest

from backend.core.upload_record_helper import infer_upload_state


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


if __name__ == '__main__':
    unittest.main()
