import unittest

from backend.core.imgbed_uploader import ImgbedUploader


class ImgbedUploaderPatternTests(unittest.TestCase):
    def test_folder_pattern_supports_extended_metadata_variables(self):
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
            folder_pattern='wallpaper/{type}/{orientation}/{category}/{color}/{primary_tag}/{originality}/{resource_id}',
        )

        folder = uploader._determine_folder(
            width=1080,
            height=1920,
            wallpaper_type='static',
            category='动漫/二次元',
            type_id='type-001',
            color_theme='蓝白',
            color_id='color-001',
            tags='少女,天空',
            is_original=True,
            resource_id='9988',
        )

        self.assertEqual(
            folder,
            'wallpaper/static/portrait/动漫_二次元/蓝白/少女/original/9988',
        )

    def test_folder_pattern_falls_back_to_untagged_when_tags_missing(self):
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
            folder_pattern='wallpaper/{type}/{tags}/{primary_tag}',
        )

        folder = uploader._determine_folder(
            width=1920,
            height=1080,
            wallpaper_type='dynamic',
            category='风景',
            tags='',
        )

        self.assertEqual(folder, 'wallpaper/dynamic/untagged/untagged')


if __name__ == '__main__':
    unittest.main()
