import unittest

from backend.core.crawler import SORT_MAP, WallpaperCrawler


class _DummyClientContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyAntiDetection:
    def build_client(self, cookie, profile=None):
        return _DummyClientContext()

    async def random_delay(self):
        return None


class _StubCrawler(WallpaperCrawler):
    def __init__(self, pages):
        super().__init__(anti_detection=_DummyAntiDetection())
        self.pages = pages

    async def _fetch_list_page(self, **kwargs):
        return self.pages.get(kwargs["page"], [])


class CrawlerIterTests(unittest.IsolatedAsyncioTestCase):
    def test_sort_map_matches_current_site_options(self):
        self.assertEqual(SORT_MAP["latest"], 1)
        self.assertEqual(SORT_MAP["most_views"], 2)
        self.assertEqual(SORT_MAP["yesterday_hot"], 3)
        self.assertEqual(SORT_MAP["3days_hot"], 4)
        self.assertEqual(SORT_MAP["7days_hot"], 5)

    async def test_iter_wallpapers_without_limit_keeps_turning_pages(self):
        crawler = _StubCrawler({
            1: [{"resource_id": "a"}, {"resource_id": "b"}],
            2: [{"resource_id": "c"}],
            3: [],
        })

        items = []
        async for item in crawler.iter_wallpapers(cookie="x", max_count=None, page_size=2):
            items.append(item["resource_id"])

        self.assertEqual(items, ["a", "b", "c"])

    async def test_iter_wallpapers_can_resume_from_specific_page(self):
        crawler = _StubCrawler({
            1: [{"resource_id": "a"}],
            2: [{"resource_id": "b"}],
            3: [{"resource_id": "c"}],
            4: [],
        })

        items = []
        async for item in crawler.iter_wallpapers(cookie="x", start_page=2, max_count=None, page_size=1):
            items.append((item["resource_id"], item["_list_page"], item["_list_index"]))

        self.assertEqual(items, [("b", 2, 1), ("c", 3, 1)])

    async def test_iter_wallpapers_respects_end_page(self):
        crawler = _StubCrawler({
            1: [{"resource_id": "a"}],
            2: [{"resource_id": "b"}],
            3: [{"resource_id": "c"}],
        })

        items = []
        async for item in crawler.iter_wallpapers(cookie="x", start_page=2, end_page=2, max_count=None, page_size=1):
            items.append(item["resource_id"])

        self.assertEqual(items, ["b"])

    async def test_iter_wallpapers_with_limit_stops_at_requested_count(self):
        crawler = _StubCrawler({
            1: [{"resource_id": "a"}, {"resource_id": "b"}],
            2: [{"resource_id": "c"}, {"resource_id": "d"}],
        })

        items = []
        async for item in crawler.iter_wallpapers(cookie="x", max_count=3, page_size=2):
            items.append(item["resource_id"])

        self.assertEqual(items, ["a", "b", "c"])

    def test_normalize_mobile_static_item_marks_static_and_mobile_route(self):
        item = WallpaperCrawler._normalize_list_item({
            "wtId": "m1",
            "fileId": "f1",
            "type": 2,
            "rw": 1080,
            "rh": 2340,
            "downCount": 12,
            "labelList": ["手机", "竖图"],
        })

        self.assertEqual(item["wallpaper_type"], "static")
        self.assertEqual(item["source_route"], "mobileViewLook")
        self.assertTrue(item["source_url"].endswith("/mobileViewLook/m1"))


if __name__ == "__main__":
    unittest.main()
