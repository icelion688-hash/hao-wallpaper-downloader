import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import imgbed_manage


class _FakeUploader:
    def __init__(self):
        self.calls = []

    async def list_files(self, **kwargs):
        self.calls.append(("list_files", kwargs))
        return {
            "files": [{"name": "wallpaper/a.webp", "metadata": {"Channel": "telegram"}}],
            "directories": ["wallpaper/static"],
            "totalCount": 1,
            "returnedCount": 1,
        }

    async def get_index_info(self, **kwargs):
        self.calls.append(("get_index_info", kwargs))
        return {"totalFiles": 12, "lastUpdated": "1754020094217"}

    async def rebuild_index(self, **kwargs):
        self.calls.append(("rebuild_index", kwargs))
        return {"success": True}

    async def delete_remote_path(self, path, *, folder=False):
        self.calls.append(("delete_remote_path", {"path": path, "folder": folder}))
        return {"success": True, "fileId": path}

    async def move_remote_path(self, path, *, dist="", folder=False):
        self.calls.append(("move_remote_path", {"path": path, "dist": dist, "folder": folder}))
        file_name = path.split("/")[-1]
        new_file_id = f"{dist}/{file_name}".strip("/")
        return {"success": True, "fileId": path, "newFileId": new_file_id}

    async def get_remote_tags(self, path):
        self.calls.append(("get_remote_tags", {"path": path}))
        return {"success": True, "fileId": path, "tags": ["风景", "蓝色"]}

    async def set_remote_tags(self, path, tags, *, action="set"):
        self.calls.append(("set_remote_tags", {"path": path, "tags": tags, "action": action}))
        return {"success": True, "fileId": path, "tags": tags}

    async def set_remote_tags_batch(self, paths, tags, *, action="set"):
        self.calls.append(("set_remote_tags_batch", {"paths": paths, "tags": tags, "action": action}))
        return {"success": True, "fileIds": paths, "tags": tags}

    async def list_channels(self):
        self.calls.append(("list_channels", {}))
        return [{"name": "tg-main"}]

    async def probe_capabilities(self):
        self.calls.append(("probe_capabilities", {}))
        return {
            "channels": True,
            "list": True,
            "manage": True,
            "checks": {
                "channels": {"ok": True, "permission": "channels"},
                "list": {"ok": True, "permission": "list"},
                "manage": {"ok": True, "permission": "manage"},
            },
        }

    async def aclose(self):
        self.calls.append(("aclose", {}))


class ImgbedManageApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(imgbed_manage.router, prefix="/api/imgbed")
        self.client = TestClient(self.app)
        self.fake_uploader = _FakeUploader()

        self.profile_patch = patch(
            "backend.api.imgbed_manage.get_upload_profile",
            return_value={"key": "compressed_webp", "enabled": True},
        )
        self.uploader_patch = patch(
            "backend.api.imgbed_manage.build_uploader_by_key",
            return_value=self.fake_uploader,
        )
        self.profile_patch.start()
        self.uploader_patch.start()

    def tearDown(self):
        self.profile_patch.stop()
        self.uploader_patch.stop()

    def test_list_endpoint_forwards_filters(self):
        response = self.client.get(
            "/api/imgbed/compressed_webp/list",
            params={
                "dir": "wallpaper/static",
                "search": "girl",
                "includeTags": "蓝色",
                "excludeTags": "NSFW",
                "recursive": "true",
                "count": 100,
                "channel": "telegram",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"]["totalCount"], 1)

        method, kwargs = self.fake_uploader.calls[0]
        self.assertEqual(method, "list_files")
        self.assertEqual(kwargs["directory"], "wallpaper/static")
        self.assertEqual(kwargs["search"], "girl")
        self.assertEqual(kwargs["include_tags"], "蓝色")
        self.assertEqual(kwargs["exclude_tags"], "NSFW")
        self.assertTrue(kwargs["recursive"])
        self.assertEqual(kwargs["count"], 100)
        self.assertEqual(kwargs["channel"], "telegram")

    def test_delete_endpoint_forwards_path_and_folder_flag(self):
        response = self.client.delete(
            "/api/imgbed/compressed_webp/delete",
            params={"path": "wallpaper/static/a.webp", "folder": "false"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

        method, kwargs = self.fake_uploader.calls[0]
        self.assertEqual(method, "delete_remote_path")
        self.assertEqual(kwargs["path"], "wallpaper/static/a.webp")
        self.assertFalse(kwargs["folder"])

    def test_index_endpoints_proxy_to_uploader(self):
        info_response = self.client.get("/api/imgbed/compressed_webp/index-info", params={"dir": "wallpaper"})
        rebuild_response = self.client.post("/api/imgbed/compressed_webp/rebuild-index", params={"dir": "wallpaper"})
        channels_response = self.client.get("/api/imgbed/compressed_webp/channels")
        capabilities_response = self.client.get("/api/imgbed/compressed_webp/capabilities")

        self.assertEqual(info_response.status_code, 200)
        self.assertEqual(info_response.json()["data"]["totalFiles"], 12)
        self.assertEqual(rebuild_response.status_code, 200)
        self.assertEqual(channels_response.status_code, 200)
        self.assertEqual(channels_response.json()["channels"][0]["name"], "tg-main")
        self.assertEqual(capabilities_response.status_code, 200)
        self.assertTrue(capabilities_response.json()["data"]["manage"])

    def test_move_and_tags_endpoints_proxy_to_uploader(self):
        move_response = self.client.post(
            "/api/imgbed/compressed_webp/move",
            json={"path": "wallpaper/static/a.webp", "dist": "wallpaper/dynamic", "folder": False},
        )
        get_tags_response = self.client.get(
            "/api/imgbed/compressed_webp/tags",
            params={"path": "wallpaper/dynamic/a.webp"},
        )
        set_tags_response = self.client.post(
            "/api/imgbed/compressed_webp/tags",
            json={"path": "wallpaper/dynamic/a.webp", "tags": ["风景", "蓝色"], "action": "set"},
        )
        batch_tags_response = self.client.post(
            "/api/imgbed/compressed_webp/tags/batch",
            json={
                "paths": ["wallpaper/dynamic/a.webp", "wallpaper/dynamic/b.webp"],
                "tags": ["风景"],
                "action": "add",
            },
        )

        self.assertEqual(move_response.status_code, 200)
        self.assertEqual(move_response.json()["data"]["newFileId"], "wallpaper/dynamic/a.webp")
        self.assertEqual(get_tags_response.status_code, 200)
        self.assertEqual(get_tags_response.json()["data"]["tags"], ["风景", "蓝色"])
        self.assertEqual(set_tags_response.status_code, 200)
        self.assertEqual(batch_tags_response.status_code, 200)
        self.assertEqual(batch_tags_response.json()["count"], 2)

        self.assertEqual(self.fake_uploader.calls[0][0], "move_remote_path")
        self.assertEqual(self.fake_uploader.calls[2][0], "get_remote_tags")
        self.assertEqual(self.fake_uploader.calls[4][0], "set_remote_tags")
        self.assertEqual(self.fake_uploader.calls[6][0], "set_remote_tags_batch")

    def test_scan_remote_duplicates_groups_same_file_identity(self):
        async def _list_files(**kwargs):
            self.fake_uploader.calls.append(("list_files", kwargs))
            return {
                "files": [
                    {
                        "name": "wallpaper/static/横图/未定义/1774530830796_励志_奋斗_7680x4320.png",
                        "metadata": {"FileName": "励志_奋斗_7680x4320.png", "FileSizeBytes": 20235346, "Width": 7680, "Height": 4320, "FileType": "image/png", "TimeStamp": 1774530830796},
                    },
                    {
                        "name": "wallpaper/static/横图/未定义/1774530684599_励志_奋斗_7680x4320.png",
                        "metadata": {"FileName": "励志_奋斗_7680x4320.png", "FileSizeBytes": 20235346, "Width": 7680, "Height": 4320, "FileType": "image/png", "TimeStamp": 1774530684599},
                    },
                ]
            }

        self.fake_uploader.list_files = _list_files

        response = self.client.post(
            "/api/imgbed/compressed_webp/duplicates/scan",
            json={"dir": ""},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_groups"], 1)
        self.assertEqual(payload["total_duplicates"], 1)
        self.assertEqual(payload["groups"][0]["duplicates"][0]["path"], "wallpaper/static/横图/未定义/1774530684599_励志_奋斗_7680x4320.png")

    def test_clean_remote_duplicates_deletes_secondary_items(self):
        async def _list_files(**kwargs):
            self.fake_uploader.calls.append(("list_files", kwargs))
            return {
                "files": [
                    {
                        "name": "wallpaper/static/横图/未定义/1774530830796_励志_奋斗_7680x4320.png",
                        "metadata": {"FileName": "励志_奋斗_7680x4320.png", "FileSizeBytes": 20235346, "Width": 7680, "Height": 4320, "FileType": "image/png", "TimeStamp": 1774530830796},
                    },
                    {
                        "name": "wallpaper/static/横图/未定义/1774530684599_励志_奋斗_7680x4320.png",
                        "metadata": {"FileName": "励志_奋斗_7680x4320.png", "FileSizeBytes": 20235346, "Width": 7680, "Height": 4320, "FileType": "image/png", "TimeStamp": 1774530684599},
                    },
                ]
            }

        self.fake_uploader.list_files = _list_files

        response = self.client.post(
            "/api/imgbed/compressed_webp/duplicates/clean",
            json={"dir": ""},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deleted_count"], 1)
        delete_calls = [call for call in self.fake_uploader.calls if call[0] == "delete_remote_path"]
        self.assertEqual(delete_calls[0][1]["path"], "wallpaper/static/横图/未定义/1774530684599_励志_奋斗_7680x4320.png")


if __name__ == "__main__":
    unittest.main()
