"""
crawler.py — 列表页爬取 + 下载直链构造

API 协议（逆向自 haowallpaper.com 前端 JS）：
  - 请求参数：JSON 序列化后 AES-CBC 加密（Key/IV 见常量），Base64 输出，作为 ?data= 查询参数
  - 响应结构：{"status":200,"msg":"成功","data":"<AES_Base64>"}
  - data 字段 AES-CBC 解密后为 JSON 字符串，列表接口格式：{"list":[...],"pages":N,"total":N}

下载 URL 规则：
  - 图片（type 1/4）：https://haowallpaper.com/link/common/file/previewFileImg/{fileId}
  - 视频（type 3）  ：https://haowallpaper.com/link/common/file/getVideoReduce/{fileId}
  - VIP 原图（需登录后有权限）：通过 GET /link/common/file/getCompleteUrl/{wtId} 获取

已知字段映射（来自 wallpaperList 响应）：
  wtId, type, userId, fileId, fileMb, typeId, colorId, sort,
  showStatus, rlevel, rw, rh, createTime, labelList, downCount, favorCount
"""

import base64
import json
import logging
from typing import AsyncIterator, Optional

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from backend.core.anti_detection import AntiDetection
from backend.core.category_map import get_category_name, get_color_name, get_color_hex

logger = logging.getLogger(__name__)

# ── API 常量 ──────────────────────────────────────────────────────────────────
BASE_URL       = "https://haowallpaper.com"
LIST_API       = "/link/pc/wallpaper/wallpaperList"
COMPLETE_URL   = "/link/common/file/getCompleteUrl"   # VIP 原图 URL 获取接口
PREVIEW_URL    = "/link/common/file/previewFileImg"   # 免费预览图（下载用）
VIDEO_URL      = "/link/common/file/getVideoReduce"   # 视频预览

# AES-CBC 参数（逆向自前端 w(G) 函数）
_AES_KEY = b"68zhehao2O776519"
_AES_IV  = b"aa176b7519e84710"

# 静态图片 type 值（参考前端 Lf 数组，1=静态图, 4=gif?）
STATIC_TYPES = {1, 4}

# 排序方式映射（sortType 数值）
SORT_MAP = {
    "yesterday_hot": 1,   # 昨日热门
    "3days_hot":     2,   # 近三天热门
    "7days_hot":     3,   # 近七天热门
    "latest":        4,   # 最新上传
    "most_views":    5,   # 最多浏览
}

# wpType 参数（逗号分隔的类型 ID 字符串）
WP_TYPE_MAP = {
    "all":     "",   # 空字符串代表全部（服务端默认）
    "static":  "1",
    "dynamic": "3",
}


# ── 加解密工具 ────────────────────────────────────────────────────────────────

def _encrypt_params(params: dict) -> str:
    """将参数字典 AES-CBC 加密后返回 Base64 字符串（用于 ?data= 查询参数）"""
    plaintext = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_IV)
    ct = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
    return base64.b64encode(ct).decode("utf-8")


def _decrypt_response(b64_cipher: str) -> str:
    """将响应 data 字段 Base64 解码后 AES-CBC 解密，返回 JSON 字符串"""
    # 补足 Base64 padding
    missing = len(b64_cipher) % 4
    if missing:
        b64_cipher += "=" * (4 - missing)
    ct = base64.b64decode(b64_cipher)
    cipher = AES.new(_AES_KEY, AES.MODE_CBC, _AES_IV)
    pt = cipher.decrypt(ct)
    # 手动去除 PKCS7 padding（兼容服务端零填充）
    pad_len = pt[-1]
    if 1 <= pad_len <= 16:
        pt = pt[:-pad_len]
    return pt.decode("utf-8").rstrip("\x00")


# ── 爬虫主类 ──────────────────────────────────────────────────────────────────

class WallpaperCrawler:
    """壁纸列表爬虫 + 下载直链构造"""

    def __init__(self, anti_detection: AntiDetection, captcha_solver=None):
        self.anti = anti_detection
        self.captcha = captcha_solver  # AltchaSolver 实例，用于 getCompleteUrl 验证

    # ── 列表爬取 ──────────────────────────────────────────────────────────────

    async def iter_wallpapers(
        self,
        cookie: str,
        category: str = "",
        sort_by: str = "yesterday_hot",
        wallpaper_type: str = "all",
        color_theme: str = "",
        max_count: int = 100,
        page_size: int = 20,
    ) -> AsyncIterator[dict]:
        """
        异步迭代器：逐页爬取壁纸列表，每次 yield 一条壁纸基本信息。

        Args:
            cookie:         账号 cookie
            category:       分类 typeId（如 "0202b9e54c3e843a4e70dc0150399d11"），空为全部
            sort_by:        排序键（见 SORT_MAP）
            wallpaper_type: "all" / "static" / "dynamic"
            color_theme:    色系 colorId，空为全部
            max_count:      最多爬取数量
            page_size:      每页条数（建议 12-20）
        """
        total_yielded = 0
        page = 1

        async with self.anti.build_client(cookie) as client:
            while total_yielded < max_count:
                batch = await self._fetch_list_page(
                    client=client,
                    cookie=cookie,
                    category=category,
                    sort_by=sort_by,
                    wallpaper_type=wallpaper_type,
                    color_theme=color_theme,
                    page=page,
                    page_size=min(page_size, max_count - total_yielded),
                )

                if not batch:
                    logger.info("[Crawler] 第 %d 页无数据，爬取结束", page)
                    break

                for item in batch:
                    if total_yielded >= max_count:
                        break
                    yield item
                    total_yielded += 1

                logger.info("[Crawler] 第 %d 页爬取 %d 条，累计 %d", page, len(batch), total_yielded)

                if len(batch) < page_size:
                    logger.info("[Crawler] 已到达最后一页")
                    break

                page += 1
                await self.anti.random_delay()

    async def _fetch_list_page(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        category: str,
        sort_by: str,
        wallpaper_type: str,
        color_theme: str,
        page: int,
        page_size: int,
    ) -> list[dict]:
        """爬取单页列表，返回规范化后的壁纸信息列表"""
        params: dict = {
            "page":       str(page),
            "sortType":   SORT_MAP.get(sort_by, 1),
            "rows":       page_size,
            "isFavorites": False,
            "wpType":     WP_TYPE_MAP.get(wallpaper_type, ""),
        }
        if category:
            params["typeId"] = category
        if color_theme:
            params["colorId"] = color_theme

        enc_data = _encrypt_params(params)
        url = f"{BASE_URL}{LIST_API}"
        headers = self.anti.build_headers(cookie)

        try:
            resp = await client.get(
                url, params={"data": enc_data}, headers=headers, timeout=15
            )
            resp.raise_for_status()
            wrapper = resp.json()

            if wrapper.get("status") != 200 or not wrapper.get("data"):
                logger.warning("[Crawler] 列表页非 200: status=%s msg=%s",
                               wrapper.get("status"), wrapper.get("msg"))
                return []

            decrypted = _decrypt_response(wrapper["data"])
            payload = json.loads(decrypted)

            # 兼容两种响应包装：直接 list 或 {"list":[], "pages":N, "total":N}
            items = payload if isinstance(payload, list) else payload.get("list", [])
            return [self._normalize_list_item(item) for item in items if item]

        except httpx.HTTPStatusError as e:
            logger.error("[Crawler] 列表页 HTTP 错误: %s", e.response.status_code)
            return []
        except Exception as e:
            logger.error("[Crawler] 列表页异常: %s", e)
            return []

    # ── 详情（下载直链）──────────────────────────────────────────────────────

    async def fetch_detail(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        resource_id: str,
        file_id: str = "",
        wallpaper_type_id: int = 1,
        skip_altcha: bool = False,
    ) -> Optional[dict]:
        """
        构造/获取壁纸下载直链。

        优先策略：
          1. 静态图（type 1/4）：altcha 验证 → getCompleteUrl 获取原图签名直链
             若无 captcha_solver 或验证失败，则回退到 previewFileImg（压缩预览）
          2. 视频（type 3）：直接使用 getVideoReduce URL

        Args:
            client:            复用的 httpx 客户端（验证与下载必须同一实例）
            cookie:            账号 cookie
            resource_id:       壁纸 wtId
            file_id:           列表中的 fileId（构造回退 URL 用）
            wallpaper_type_id: 壁纸类型 int（1=图片, 3=视频）
            skip_altcha:       True 时跳过 altcha 重新验证（复用已验证的 client session）

        Returns:
            包含 download_url 的字典，或 None
        """
        # 视频直接用 getVideoReduce，无需验证
        if wallpaper_type_id not in STATIC_TYPES:
            if file_id:
                return {
                    "resource_id": resource_id,
                    "download_url": f"{BASE_URL}{VIDEO_URL}/{file_id}",
                    "is_original": False,
                }
            return None

        # 静态图：优先走 altcha + getCompleteUrl 获取原图
        complete = await self._fetch_complete_url(client, cookie, resource_id, skip_altcha=skip_altcha)
        if complete:
            return complete

        # 回退：直接使用 previewFileImg（压缩预览，约 70KB）
        if file_id:
            logger.warning("[Crawler] 回退至 previewFileImg: %s", resource_id)
            return {
                "resource_id": resource_id,
                "download_url": f"{BASE_URL}{PREVIEW_URL}/{file_id}",
                "is_original": False,
            }

        return None

    async def _fetch_complete_url(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        resource_id: str,
        skip_altcha: bool = False,
    ) -> Optional[dict]:
        """
        altcha 人机验证 → getCompleteUrl 获取原图签名直链。

        必须使用同一 client 实例完成验证和取链两步，服务端通过 session cookie
        判断是否已通过验证。失败时返回 None，调用方应回退到 previewFileImg。

        Args:
            skip_altcha: True 时跳过 altcha 重验证，直接调用 getCompleteUrl
                         （适用于任务级复用同一 client session 的场景）
        """
        import urllib.parse
        import re as _re

        # 从 cookie 中提取 token（兼容 '; ' 和 ',' 两种分隔符）
        token = ""
        _m = _re.search(r'userData=([^;,]+)', cookie)
        if _m:
            try:
                val = urllib.parse.unquote(_m.group(1).strip())
                token = json.loads(val).get("token", "")
            except Exception as _e:
                logger.warning("[Crawler] userData token 提取失败: %s", _e)

        # Step 1: altcha 验证（skip_altcha=True 时跳过，复用已有 session）
        if not skip_altcha:
            if self.captcha:
                verified = await self.captcha.verify_download(client, cookie)
                if not verified:
                    logger.warning("[Crawler] altcha 验证失败，无法获取原图: %s", resource_id)
                    return None
            else:
                logger.debug("[Crawler] 未配置 captcha_solver，跳过验证")
                return None

        # Step 2: getCompleteUrl（验证后立即调用，签名 URL 很快过期）
        headers = self.anti.build_headers(cookie)
        headers["token"] = token
        headers["Cache-Control"] = "no-cache"
        url = f"{BASE_URL}{COMPLETE_URL}/{resource_id}"

        try:
            resp = await client.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                wrapper = resp.json()
                if wrapper.get("status") == 200 and wrapper.get("data"):
                    download_url = wrapper["data"]  # 带签名的 CDN 直链
                    logger.info("[Crawler] 原图直链获取成功: %s", resource_id)
                    return {
                        "resource_id": resource_id,
                        "download_url": download_url,
                        "is_original": True,
                    }
            logger.warning("[Crawler] getCompleteUrl %s 返回: status=%s body=%s",
                           resource_id, resp.status_code, resp.text[:100])
        except Exception as e:
            logger.error("[Crawler] getCompleteUrl %s 异常: %s", resource_id, e)

        return None

    # ── 数据规范化 ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_list_item(raw: dict) -> dict:
        """将 wallpaperList 返回的原始字段规范化为统一格式"""
        wt_id   = str(raw.get("wtId") or "")
        file_id = str(raw.get("fileId") or "")
        wtype   = int(raw.get("type") or 1)

        # 静态图留空，由 fetch_detail 走 altcha+getCompleteUrl 获取原图直链
        # 视频直接构造 getVideoReduce URL（无需验证）
        if wtype in STATIC_TYPES:
            download_url = ""
        else:
            download_url = f"{BASE_URL}{VIDEO_URL}/{file_id}" if file_id else ""

        # 分类 / 色系：保留原始 UUID + 映射为可读名称
        type_id  = str(raw.get("typeId")  or "")
        color_id = str(raw.get("colorId") or "")
        category_name = get_category_name(type_id)   # 如"动漫｜二次元"，未知则空字符串
        color_name    = get_color_name(color_id)      # 如"偏蓝"，未知则空字符串

        tags = raw.get("labelList") or []
        down_count  = _safe_int(raw.get("downCount"))
        favor_count = _safe_int(raw.get("favorCount"))

        return {
            "resource_id":    wt_id,
            "file_id":        file_id,
            "title":          "",    # wallpaperList 不返回标题字段
            # type_id UUID：用于 API 级过滤（传给 iter_wallpapers 的 category 参数）
            "type_id":        type_id,
            "color_id":       color_id,
            # 可读名称：用于存储到 DB、日志、文件夹命名
            "category_name":  category_name,
            "color_name":     color_name,
            # 兼容旧代码（category 字段），下游 tasks.py 会再做优先级判断
            "category":       type_id,
            "wallpaper_type": "dynamic" if wtype not in STATIC_TYPES else "static",
            "width":          _safe_int(raw.get("rw")),
            "height":         _safe_int(raw.get("rh")),
            "hot_score":      down_count,   # 下载数作为热度分（与 min_hot_score 比较）
            "down_count":     down_count,
            "favor_count":    favor_count,
            "tags":           ",".join(tags) if isinstance(tags, list) else str(tags),
            "thumbnail_url":  f"{BASE_URL}/link/common/file/getCroppingImg/{file_id}" if file_id else "",
            "download_url":   download_url,
            "source_url":     f"{BASE_URL}/wallpaper/{wt_id}",
            "file_mb":        str(raw.get("fileMb") or ""),
            "create_time":    str(raw.get("createTime") or ""),
        }


def _safe_int(val) -> Optional[int]:
    """安全转 int，失败返回 None"""
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
