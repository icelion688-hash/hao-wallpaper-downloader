import unittest

from backend.api.tasks import _resolve_upload_profile_key


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


if __name__ == "__main__":
    unittest.main()
