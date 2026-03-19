import unittest

from backend.api.tasks import (
    _format_prefilter_summary,
    _get_wallpaper_orientation,
    _has_mixed_static_orientations,
    _resolve_source_scopes,
    _select_diversified_candidates,
)


class TaskCandidateSelectionTests(unittest.TestCase):
    def test_select_diversified_candidates_preserves_mix_when_portrait_exists(self):
        candidates = [
            {"resource_id": "l1", "width": 3840, "height": 2160, "wallpaper_type": "static"},
            {"resource_id": "l2", "width": 2560, "height": 1440, "wallpaper_type": "static"},
            {"resource_id": "l3", "width": 1920, "height": 1080, "wallpaper_type": "static"},
            {"resource_id": "p1", "width": 1440, "height": 2560, "wallpaper_type": "static"},
            {"resource_id": "l4", "width": 1600, "height": 900, "wallpaper_type": "static"},
            {"resource_id": "p2", "width": 1080, "height": 1920, "wallpaper_type": "static"},
        ]

        selected = _select_diversified_candidates(candidates, 4)
        selected_ids = [item["resource_id"] for item in selected]
        orientations = [_get_wallpaper_orientation(item) for item in selected]

        self.assertEqual(len(selected_ids), 4)
        self.assertIn("portrait", orientations)
        self.assertIn("landscape", orientations)
        self.assertEqual(selected_ids[0], "l1")

    def test_select_diversified_candidates_falls_back_to_original_order_when_no_portrait(self):
        candidates = [
            {"resource_id": "l1", "width": 3840, "height": 2160, "wallpaper_type": "static"},
            {"resource_id": "l2", "width": 2560, "height": 1440, "wallpaper_type": "static"},
            {"resource_id": "l3", "width": 1920, "height": 1080, "wallpaper_type": "static"},
        ]

        selected = _select_diversified_candidates(candidates, 2)

        self.assertEqual([item["resource_id"] for item in selected], ["l1", "l2"])
        self.assertFalse(_has_mixed_static_orientations(selected))

    def test_format_prefilter_summary_keeps_log_compact(self):
        line = _format_prefilter_summary(
            label="预筛跳过(不符合筛选)",
            batch_count=20,
            total_count=125,
            latest_resource_id="abc123",
            latest_reason="热度不足: 12 < 100",
        )

        self.assertEqual(
            line,
            "预筛跳过(不符合筛选): 本轮 20 张，累计 125 张 | 最近资源 abc123 | 最近原因 热度不足: 12 < 100",
        )

    def test_resolve_source_scopes_for_static_all_includes_desktop_and_mobile(self):
        class _Cfg:
            wallpaper_type = "static"
            screen_orientation = "all"

        self.assertEqual(_resolve_source_scopes(_Cfg()), ["desktop_static", "mobile_static"])


if __name__ == "__main__":
    unittest.main()
