import unittest

from backend.api.gallery import _build_cleanup_reason


class GalleryCleanupReasonTests(unittest.TestCase):
    def test_keep_count_reason_when_nothing_to_delete(self):
        reason = _build_cleanup_reason(
            strategy="keep_count",
            total_eligible=120,
            delete_count=0,
            max_count=500,
            keep_days=30,
            uploaded_only=True,
        )
        self.assertIn("未超过保留上限 500 张", reason)

    def test_keep_days_reason_when_deleting_files(self):
        reason = _build_cleanup_reason(
            strategy="keep_days",
            total_eligible=42,
            delete_count=12,
            max_count=500,
            keep_days=30,
            uploaded_only=False,
        )
        self.assertIn("最近 30 天之外", reason)


if __name__ == "__main__":
    unittest.main()
