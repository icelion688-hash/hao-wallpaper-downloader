import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from backend.core.imgbed_uploader import ImgbedUploader


class ImgbedUploaderPatternTests(unittest.TestCase):
    def setUp(self):
        ImgbedUploader._MANAGE_TRANSPORT_HINTS.clear()

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

    def test_request_json_falls_back_to_curl_when_httpx_connect_error(self):
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
        )
        fake_client = AsyncMock()
        fake_client.request.side_effect = httpx.ConnectError('握手失败')

        async def _run():
            with patch.object(uploader, '_ensure_client', return_value=fake_client):
                with patch.object(
                    uploader,
                    '_request_json_via_curl',
                    AsyncMock(return_value={'files': []}),
                ) as fallback:
                    result = await uploader._request_json('GET', '/api/manage/list', params={'count': 1})
            return result, fallback

        result, fallback = asyncio.run(_run())
        self.assertEqual(result, {'files': []})
        fallback.assert_awaited_once()
        self.assertEqual(ImgbedUploader._MANAGE_TRANSPORT_HINTS['https://img.example.com'], 'curl')

    def test_request_json_via_curl_parses_json_payload(self):
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
        )

        class _FakeProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b'{"success": true, "files": []}\n__CURL_HTTP_STATUS__:200',
                    b'',
                )

        async def _run():
            with patch(
                'backend.core.imgbed_uploader.asyncio.create_subprocess_exec',
                AsyncMock(return_value=_FakeProcess()),
            ):
                return await uploader._request_json_via_curl(
                    'GET',
                    'https://img.example.com/api/manage/list',
                    params={'count': 1},
                )

        result = asyncio.run(_run())
        self.assertTrue(result['success'])
        self.assertEqual(result['files'], [])

    def test_request_json_via_curl_includes_json_body_for_post(self):
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
        )

        class _FakeProcess:
            returncode = 0

            async def communicate(self):
                return (
                    b'{"success": true}\n__CURL_HTTP_STATUS__:200',
                    b'',
                )

        async def _run():
            with patch(
                'backend.core.imgbed_uploader.asyncio.create_subprocess_exec',
                AsyncMock(return_value=_FakeProcess()),
            ) as create_exec:
                result = await uploader._request_json_via_curl(
                    'POST',
                    'https://img.example.com/api/manage/tags/a.webp',
                    json_body={'action': 'set', 'tags': ['风景']},
                )
            return result, create_exec

        result, create_exec = asyncio.run(_run())
        self.assertTrue(result['success'])
        command = create_exec.await_args.args
        self.assertIn('--data-raw', command)
        self.assertIn('{"action": "set", "tags": ["风景"]}', command)

    def test_request_json_uses_cached_curl_preference(self):
        ImgbedUploader._MANAGE_TRANSPORT_HINTS['https://img.example.com'] = 'curl'
        uploader = ImgbedUploader(
            base_url='https://img.example.com',
            api_token='token',
        )

        async def _run():
            with patch.object(uploader, '_ensure_client') as ensure_client:
                with patch.object(
                    uploader,
                    '_request_json_via_curl',
                    AsyncMock(return_value={'success': True}),
                ) as fallback:
                    result = await uploader._request_json('GET', '/api/channels')
            return result, fallback, ensure_client

        result, fallback, ensure_client = asyncio.run(_run())
        self.assertTrue(result['success'])
        fallback.assert_awaited_once()
        ensure_client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
