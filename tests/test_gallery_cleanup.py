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
        self.assertIn("30 天前下载", reason)
        self.assertIn("12 张", reason)

    def test_keep_count_excess_all_not_uploaded(self):
        """超额但全部未上传时，应给出明确提示而非错误地说未超上限。"""
        reason = _build_cleanup_reason(
            strategy="keep_count",
            total_eligible=600,
            delete_count=0,
            max_count=500,
            keep_days=30,
            uploaded_only=True,
            skipped_not_uploaded=100,
        )
        self.assertIn("超额", reason)
        self.assertIn("未上传", reason)

    def test_keep_count_partial_skip(self):
        """超额部分有已上传也有未上传时，reason 应体现跳过数量。"""
        reason = _build_cleanup_reason(
            strategy="keep_count",
            total_eligible=600,
            delete_count=60,
            max_count=500,
            keep_days=30,
            uploaded_only=True,
            skipped_not_uploaded=40,
        )
        self.assertIn("60 张", reason)
        self.assertIn("40 张", reason)
        self.assertIn("未上传", reason)


if __name__ == "__main__":
    unittest.main()
