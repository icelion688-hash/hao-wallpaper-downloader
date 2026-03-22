import unittest

from backend.core.upload_record_helper import (
    build_remote_file_url,
    build_remote_tags,
    parse_remote_file_id_from_url,
)


class UploadRecordHelperTests(unittest.TestCase):
    def test_remote_file_url_round_trip(self):
        url = build_remote_file_url('https://img.example.com', 'wallpaper/static/风景/a.webp')
        self.assertEqual(
            url,
            'https://img.example.com/file/wallpaper/static/%E9%A3%8E%E6%99%AF/a.webp',
        )
        self.assertEqual(parse_remote_file_id_from_url(url), 'wallpaper/static/风景/a.webp')

    def test_build_remote_tags_merges_structured_and_custom_tags(self):
        tags = build_remote_tags(
            width=1920,
            height=1080,
            wallpaper_type='static',
            category='风景',
            color_theme='蓝色',
            tags='风景, 蓝色, 山川',
        )
        self.assertEqual(tags, ['静态图', '横图', '风景', '蓝色', '山川'])


if __name__ == '__main__':
    unittest.main()
