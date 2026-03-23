import os
import shutil
import tempfile
import unittest
import asyncio

from backend.core.autopilot_engine import AutoPilotEngine


class AutoPilotCursorTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cursor_state_persists(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)
        key = engine._build_cursor_key({
            "wallpaper_type": "static",
            "sort_by": "yesterday_hot",
            "categories": [],
            "color_themes": [],
            "vip_only": True,
            "min_hot_score": 100,
            "tag_blacklist": [],
            "min_width": None,
            "min_height": None,
            "screen_orientation": "all",
        })
        engine._cursor_state[key] = 12
        engine._save_cursor_state()

        reloaded = AutoPilotEngine(data_dir=self.tmpdir)
        self.assertEqual(reloaded._cursor_state.get(key), 12)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "autopilot_cursor.json")))


class AutoPilotConfigTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_update_config_normalizes_ranges(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)

        config = engine.update_config({
            "active_session_min": 20,
            "active_session_max": 5,
            "active_interval_min": 7200,
            "active_interval_max": 1800,
            "inactive_session_min": 10,
            "inactive_session_max": 2,
            "inactive_interval_min": 14400,
            "inactive_interval_max": 120,
        })

        self.assertEqual((config["active_session_min"], config["active_session_max"]), (5, 20))
        self.assertEqual((config["active_interval_min"], config["active_interval_max"]), (1800, 7200))
        self.assertEqual((config["inactive_session_min"], config["inactive_session_max"]), (2, 10))
        self.assertEqual((config["inactive_interval_min"], config["inactive_interval_max"]), (120, 14400))

    def test_update_config_keeps_storage_and_upload_profile_fields(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)

        config = engine.update_config({
            "use_imgbed_upload": True,
            "static_upload_profile": "compressed_webp",
            "dynamic_upload_profile": "original_lossless",
            "storage_auto_clean": True,
            "storage_strategy": "keep_days",
            "storage_keep_days": 14,
            "storage_uploaded_only": False,
        })

        self.assertTrue(config["use_imgbed_upload"])
        self.assertEqual(config["static_upload_profile"], "compressed_webp")
        self.assertEqual(config["dynamic_upload_profile"], "original_lossless")
        self.assertTrue(config["storage_auto_clean"])
        self.assertEqual(config["storage_strategy"], "keep_days")
        self.assertEqual(config["storage_keep_days"], 14)
        self.assertFalse(config["storage_uploaded_only"])

    async def test_update_config_interrupts_waiting_sleep(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)
        engine._status = "running"

        sleep_task = asyncio.create_task(engine._interruptible_sleep(30))
        await asyncio.sleep(0.05)
        engine.update_config({
            "active_interval_min": 60,
            "active_interval_max": 120,
        })

        interrupted = await asyncio.wait_for(sleep_task, timeout=1)
        self.assertTrue(interrupted)

    def test_get_status_includes_storage_cleanup_state(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)
        engine._record_storage_cleanup_state(
            trigger="session",
            skipped=False,
            reason="将保留最新 500 张，其余符合条件的本地文件会被清理",
            result={
                "strategy": "keep_count",
                "uploaded_only": True,
                "deleted": 12,
                "remaining": 88,
                "total_eligible": 100,
                "file_fail_count": 0,
            },
        )

        status = engine.get_status()

        self.assertIn("storage", status)
        self.assertEqual(status["storage"]["strategy"], "keep_count")
        self.assertEqual(status["storage"]["last_cleanup"]["deleted"], 12)
        self.assertEqual(status["storage"]["last_cleanup"]["remaining"], 88)
        self.assertFalse(status["storage"]["last_cleanup"]["skipped"])

    def test_get_status_includes_storage_cleanup_skip_reason(self):
        engine = AutoPilotEngine(data_dir=self.tmpdir)
        engine._record_storage_cleanup_state(
            trigger="session",
            skipped=True,
            reason="本次会话没有新增下载文件，已跳过自动清理",
        )

        status = engine.get_status()

        self.assertTrue(status["storage"]["last_cleanup"]["skipped"])
        self.assertIn("跳过", status["storage"]["last_cleanup"]["reason"])


if __name__ == "__main__":
    unittest.main()
