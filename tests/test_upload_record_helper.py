import asyncio
import unittest

from backend.core.upload_record_helper import (
    build_remote_file_url,
    build_remote_tags,
    extract_local_tags_from_remote,
    normalize_remote_tag,
    parse_remote_file_id_from_url,
    sync_remote_record_metadata,
)


class _FakeUploader:
    def __init__(self):
        self.calls = []

    async def set_remote_tags(self, path, tags, *, action='set'):
        self.calls.append((path, tags, action))
        return {'success': True}


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
            category='风景｜山川',
            color_theme='灰/白',
            tags='风景, 蓝色, 山川',
        )
        self.assertEqual(tags, ['静态图', '横图', '风景_山川', '灰_白', '风景', '蓝色', '山川'])

    def test_normalize_remote_tag_replaces_invalid_chars(self):
        self.assertEqual(normalize_remote_tag('动漫｜二次元'), '动漫_二次元')
        self.assertEqual(normalize_remote_tag('灰/白'), '灰_白')

    def test_extract_local_tags_from_remote_strips_structured_tags(self):
        tags = extract_local_tags_from_remote(
            width=1920,
            height=1080,
            wallpaper_type='static',
            category='风景｜山川',
            color_theme='灰/白',
            remote_tags=['静态图', '横图', '风景_山川', '灰_白', '蓝色', '山川'],
        )
        self.assertEqual(tags, ['蓝色', '山川'])

    def test_sync_remote_record_metadata_can_skip_remote_tag_write(self):
        uploader = _FakeUploader()
        result = asyncio.run(
            sync_remote_record_metadata(
                uploader,
                url='https://img.example.com/file/wallpaper/static/a.webp',
                width=1920,
                height=1080,
                wallpaper_type='static',
                category='风景',
                color_theme='蓝色',
                tags='天空',
                sync_tags=False,
            )
        )

        self.assertEqual(result['remote_path'], 'wallpaper/static/a.webp')
        self.assertEqual(result['remote_tags'], [])
        self.assertFalse(result['tag_sync_success'])
        self.assertEqual(uploader.calls, [])


if __name__ == '__main__':
    unittest.main()
