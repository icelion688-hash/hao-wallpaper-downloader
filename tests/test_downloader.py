import unittest

from backend.core.downloader import Downloader


class DownloaderPathTests(unittest.TestCase):
    def test_static_wallpaper_keeps_category_root(self):
        category = Downloader._resolve_save_category(
            category="动漫｜二次元",
            wallpaper_type="static",
            width=3840,
            height=2160,
        )
        self.assertEqual(category, "动漫｜二次元")

    def test_dynamic_wallpaper_uses_landscape_subdir(self):
        category = Downloader._resolve_save_category(
            category="动漫｜二次元",
            wallpaper_type="dynamic",
            width=3840,
            height=2160,
        )
        self.assertEqual(category, "动漫｜二次元/横图")

    def test_dynamic_wallpaper_uses_portrait_subdir(self):
        category = Downloader._resolve_save_category(
            category="动漫｜二次元",
            wallpaper_type="dynamic",
            width=1080,
            height=1920,
        )
        self.assertEqual(category, "动漫｜二次元/竖图")

    def test_dynamic_wallpaper_without_category_falls_back_to_orientation(self):
        category = Downloader._resolve_save_category(
            category="",
            wallpaper_type="dynamic",
            width=1080,
            height=1080,
        )
        self.assertEqual(category, "方图")


if __name__ == "__main__":
    unittest.main()
