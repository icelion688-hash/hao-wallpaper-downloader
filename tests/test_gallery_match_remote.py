import unittest

from backend.api.gallery import _match_remote_wallpapers, _pick_upload_record_entry
from backend.core.upload_record_helper import build_upload_record, dump_upload_records
from backend.models.wallpaper import Wallpaper


class GalleryMatchRemoteTests(unittest.TestCase):
    def test_match_remote_prefers_file_identity_not_directory(self):
        wallpaper = Wallpaper(
            id=1,
            resource_id='17603630336822656',
            title='测试壁纸',
            wallpaper_type='static',
            category='动漫｜二次元',
            color_theme='蓝色',
            tags='少女,夜景',
            local_path='动漫｜二次元/17603630336822656.jpg',
            imgbed_url='https://img.example.com/file/wallpaper/static/landscape/动漫_二次元/17603630336822656.jpg',
            upload_records=dump_upload_records({
                'compressed_webp': build_upload_record(
                    profile_key='compressed_webp',
                    profile_name='默认图床',
                    channel='telegram',
                    url='https://img.example.com/file/wallpaper/static/landscape/动漫_二次元/17603630336822656.jpg',
                    remote_path='wallpaper/static/landscape/动漫_二次元/17603630336822656.jpg',
                ),
            }),
            width=1920,
            height=1080,
        )

        result = _match_remote_wallpapers(
            ['wallpaper/archive/2026/03/17603630336822656.jpg'],
            [wallpaper],
            base_url='https://img.example.com',
        )

        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['unmatched_count'], 0)
        meta = result['matched']['wallpaper/archive/2026/03/17603630336822656.jpg']
        self.assertEqual(meta['resource_id'], '17603630336822656')
        self.assertEqual(meta['matched_by'], 'file_name')
        self.assertIn('横图', meta['suggested_tags'])

    def test_match_remote_uses_exact_remote_path_when_available(self):
        wallpaper = Wallpaper(
            id=2,
            resource_id='9988',
            title='测试动态图',
            wallpaper_type='dynamic',
            category='风景',
            color_theme='绿色',
            tags='森林',
            imgbed_url='https://img.example.com/file/wallpaper/dynamic/风景/demo.webp',
            width=1080,
            height=1920,
        )

        result = _match_remote_wallpapers(
            ['wallpaper/dynamic/风景/demo.webp'],
            [wallpaper],
            base_url='https://img.example.com',
        )

        self.assertEqual(result['matched_count'], 1)
        meta = result['matched']['wallpaper/dynamic/风景/demo.webp']
        self.assertEqual(meta['matched_by'], 'exact_remote_path')
        self.assertEqual(meta['wallpaper_type'], 'dynamic')

    def test_pick_upload_record_entry_prefers_matching_profile(self):
        records = {
            'original_lossless': {
                'profile_key': 'original_lossless',
                'url': 'https://img.example.com/file/bg/pc/demo.png',
            },
            'other_profile': {
                'profile_key': 'other_profile',
                'url': 'https://img.example.com/file/other/demo.png',
            },
        }
        record_key, record, error = _pick_upload_record_entry(records, 'original_lossless', 'wallpaper/static/demo.png')
        self.assertEqual(record_key, 'original_lossless')
        self.assertEqual(record['profile_key'], 'original_lossless')
        self.assertEqual(error, '')


if __name__ == '__main__':
    unittest.main()
