import unittest

from backend.api.tasks import (
    _TASK_LOG_MAX_LINES,
    _build_retry_item,
    _classify_retry_policy,
    _split_task_log_lines,
)
from backend.models.wallpaper import Wallpaper


class TaskRetryPolicyTests(unittest.TestCase):
    def test_split_task_log_lines_keeps_latest_lines(self):
        log_text = "\n".join(f"line-{idx}" for idx in range(_TASK_LOG_MAX_LINES + 20))

        lines = _split_task_log_lines(log_text)

        self.assertEqual(len(lines), _TASK_LOG_MAX_LINES)
        self.assertEqual(lines[0], "line-20")
        self.assertEqual(lines[-1], f"line-{_TASK_LOG_MAX_LINES + 19}")

    def test_classify_retry_policy_marks_altcha_failure_retryable(self):
        retryable, retry_group, delay_seconds = _classify_retry_policy(
            "challenge 获取失败",
            "original_access",
        )

        self.assertTrue(retryable)
        self.assertEqual(retry_group, "original_access")
        self.assertGreater(delay_seconds, 0)

    def test_classify_retry_policy_rejects_filesystem_failure(self):
        retryable, retry_group, delay_seconds = _classify_retry_policy(
            "磁盘剩余空间不足",
            "filesystem",
        )

        self.assertFalse(retryable)
        self.assertEqual(retry_group, "")
        self.assertEqual(delay_seconds, 0)

    def test_build_retry_item_restores_payload(self):
        wallpaper = Wallpaper(
            resource_id="123",
            title="测试壁纸",
            wallpaper_type="static",
            retry_count=2,
            retry_payload='{"resource_id":"123","title":"测试壁纸","wallpaper_type":"static"}',
            last_error="下载超时",
        )
        wallpaper.id = 7

        item = _build_retry_item(wallpaper)

        self.assertEqual(item["resource_id"], "123")
        self.assertTrue(item["_from_retry_queue"])
        self.assertEqual(item["_retry_count"], 2)
        self.assertEqual(item["_retry_wallpaper_id"], 7)
        self.assertEqual(item["_last_error"], "下载超时")


if __name__ == "__main__":
    unittest.main()
