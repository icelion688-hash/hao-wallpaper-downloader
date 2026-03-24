import unittest

from backend.api.tasks import (
    _build_original_cooldown_message,
    _classify_static_preview_fallback,
    _determine_original_cooldown_seconds,
    _format_prefilter_summary,
    _get_wallpaper_orientation,
    _has_mixed_static_orientations,
    _resolve_source_scopes,
    _select_diversified_candidates,
    _should_skip_original_retry,
    _summarize_original_failure_reason,
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

    def test_classify_static_preview_fallback_downgrades_vip_preview(self):
        self.assertEqual(
            _classify_static_preview_fallback(account_type="vip", login_valid=True),
            "downgrade_preview",
        )

    def test_classify_static_preview_fallback_rejects_invalid_login(self):
        self.assertEqual(
            _classify_static_preview_fallback(account_type="vip", login_valid=False),
            "invalid_login",
        )

    def test_summarize_original_failure_reason_for_challenge_305(self):
        self.assertEqual(
            _summarize_original_failure_reason("challenge 请求失败: HTTP 305"),
            "altcha challenge 被站点限流(305)",
        )

    def test_should_skip_original_retry_for_challenge_305(self):
        self.assertTrue(_should_skip_original_retry("challenge 请求失败: HTTP 305"))

    def test_determine_original_cooldown_seconds_for_rate_limits(self):
        self.assertEqual(_determine_original_cooldown_seconds("challenge 请求失败: HTTP 305"), 180)
        self.assertEqual(_determine_original_cooldown_seconds("verify HTTP 305"), 120)
        self.assertEqual(_determine_original_cooldown_seconds("getCompleteUrl HTTP 305"), 90)

    def test_build_original_cooldown_message_is_human_readable(self):
        message = _build_original_cooldown_message("challenge 请求失败: HTTP 305", 12.2)
        self.assertEqual(message, "原图链路冷却中，剩余 13 秒 | altcha challenge 被站点限流(305)")


if __name__ == "__main__":
    unittest.main()
