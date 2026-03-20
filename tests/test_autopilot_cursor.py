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


if __name__ == "__main__":
    unittest.main()
