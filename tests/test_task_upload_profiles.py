import unittest

from backend.api.tasks import (
    _resolve_active_upload_profile_key,
    _resolve_upload_channel_override,
    _resolve_upload_profile_key,
)


class TaskUploadProfileTests(unittest.TestCase):
    def test_static_prefers_static_profile(self):
        profile_key = _resolve_upload_profile_key(
            {
                "static_upload_profile": "compressed_webp",
                "dynamic_upload_profile": "original_lossless",
            },
            "static",
            fallback_profile_key="fallback_profile",
        )
        self.assertEqual(profile_key, "compressed_webp")

    def test_dynamic_prefers_dynamic_profile(self):
        profile_key = _resolve_upload_profile_key(
            {
                "static_upload_profile": "compressed_webp",
                "dynamic_upload_profile": "original_lossless",
            },
            "dynamic",
            fallback_profile_key="fallback_profile",
        )
        self.assertEqual(profile_key, "original_lossless")

    def test_missing_dynamic_profile_falls_back_to_static_profile(self):
        profile_key = _resolve_upload_profile_key(
            {
                "static_upload_profile": "compressed_webp",
                "dynamic_upload_profile": "",
            },
            "dynamic",
            fallback_profile_key="fallback_profile",
        )
        self.assertEqual(profile_key, "compressed_webp")

    def test_missing_both_profiles_uses_fallback(self):
        profile_key = _resolve_upload_profile_key(
            {},
            "dynamic",
            fallback_profile_key="fallback_profile",
        )
        self.assertEqual(profile_key, "fallback_profile")

    def test_unavailable_selected_profile_falls_back_to_default_profile(self):
        profile_key, fallback_from = _resolve_active_upload_profile_key(
            {
                "static_upload_profile": "compressed_webp",
                "dynamic_upload_profile": "original_lossless",
            },
            "static",
            fallback_profile_key="original_lossless",
            profile_available_checker=lambda key: key == "original_lossless",
        )
        self.assertEqual(profile_key, "original_lossless")
        self.assertEqual(fallback_from, "compressed_webp")

    def test_unavailable_selected_profile_without_usable_fallback_keeps_selected_key(self):
        profile_key, fallback_from = _resolve_active_upload_profile_key(
            {
                "static_upload_profile": "compressed_webp",
                "dynamic_upload_profile": "",
            },
            "static",
            fallback_profile_key="original_lossless",
            profile_available_checker=lambda key: False,
        )
        self.assertEqual(profile_key, "compressed_webp")
        self.assertEqual(fallback_from, "")

    def test_static_channel_override_prefers_static_values(self):
        channel, channel_name = _resolve_upload_channel_override(
            {
                "static_upload_channel": "telegram",
                "static_upload_channel_name": "tg-a",
                "dynamic_upload_channel": "s3",
                "dynamic_upload_channel_name": "bucket-a",
            },
            "static",
        )
        self.assertEqual(channel, "telegram")
        self.assertEqual(channel_name, "tg-a")

    def test_dynamic_channel_override_prefers_dynamic_values(self):
        channel, channel_name = _resolve_upload_channel_override(
            {
                "static_upload_channel": "telegram",
                "dynamic_upload_channel": "s3",
                "dynamic_upload_channel_name": "bucket-a",
            },
            "dynamic",
        )
        self.assertEqual(channel, "s3")
        self.assertEqual(channel_name, "bucket-a")

    def test_dynamic_channel_override_does_not_fall_back_to_static_override(self):
        channel, channel_name = _resolve_upload_channel_override(
            {
                "static_upload_channel": "telegram",
                "static_upload_channel_name": "tg-a",
                "dynamic_upload_channel": "",
                "dynamic_upload_channel_name": "",
            },
            "dynamic",
        )
        self.assertEqual(channel, "")
        self.assertEqual(channel_name, "")

    def test_static_channel_override_does_not_fall_back_to_dynamic_override(self):
        channel, channel_name = _resolve_upload_channel_override(
            {
                "static_upload_channel": "",
                "static_upload_channel_name": "",
                "dynamic_upload_channel": "s3",
                "dynamic_upload_channel_name": "bucket-a",
            },
            "static",
        )
        self.assertEqual(channel, "")
        self.assertEqual(channel_name, "")


if __name__ == "__main__":
    unittest.main()
