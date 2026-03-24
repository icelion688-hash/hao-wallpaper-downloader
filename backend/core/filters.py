"""
filters.py — 壁纸筛选规则引擎

根据用户在前端配置的规则，对爬取到的壁纸元数据进行过滤：
  - 壁纸类型（静态/动态）
  - 分辨率范围
  - 分类（动漫、风景等）
  - 色系
  - 热度分阈值
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """筛选规则配置"""

    # 壁纸类型: "all" | "static" | "dynamic"
    wallpaper_type: str = "all"

    # 分类白名单（空列表表示不限）
    categories: list[str] = field(default_factory=list)

    # 分辨率范围（宽或高，单位 px）
    min_width: Optional[int] = None
    max_width: Optional[int] = None
    min_height: Optional[int] = None
    max_height: Optional[int] = None

    # 色系白名单（空列表表示不限）
    color_themes: list[str] = field(default_factory=list)

    # 热度分阈值（0 表示不限）
    min_hot_score: int = 0

    # 标签黑名单（包含这些标签的壁纸被过滤掉）
    tag_blacklist: list[str] = field(default_factory=list)

    # 最小文件大小（字节，0 表示不限）
    min_file_size: int = 0

    # 屏幕方向: "all" | "landscape"（电脑横屏, w>=h）| "portrait"（手机竖屏, h>w）
    screen_orientation: str = "all"

    # 排序方式（传给爬虫 API）
    sort_by: str = "yesterday_hot"

    # 最大下载数量
    max_count: int = 100

    # 并发下载数
    concurrency: int = 3

    # 仅使用 VIP 账号
    vip_only: bool = False

    # 是否启用代理
    use_proxy: bool = True

    # 严格原图模式：未拿到原图则跳过，不接受预览图降级
    strict_original: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "FilterConfig":
        """从字典反序列化（来自任务配置 JSON）"""
        return cls(
            wallpaper_type=d.get("wallpaper_type", "all"),
            categories=d.get("categories", []),
            min_width=d.get("min_width"),
            max_width=d.get("max_width"),
            min_height=d.get("min_height"),
            max_height=d.get("max_height"),
            color_themes=d.get("color_themes", []),
            min_hot_score=d.get("min_hot_score", 0),
            tag_blacklist=d.get("tag_blacklist", []),
            min_file_size=d.get("min_file_size", 0),
            screen_orientation=d.get("screen_orientation", "all"),
            sort_by=d.get("sort_by", "yesterday_hot"),
            max_count=d.get("max_count", 100),
            concurrency=d.get("concurrency", 3),
            vip_only=d.get("vip_only", False),
            use_proxy=d.get("use_proxy", True),
            strict_original=d.get("strict_original", False),
        )

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "wallpaper_type": self.wallpaper_type,
            "categories": self.categories,
            "min_width": self.min_width,
            "max_width": self.max_width,
            "min_height": self.min_height,
            "max_height": self.max_height,
            "color_themes": self.color_themes,
            "min_hot_score": self.min_hot_score,
            "tag_blacklist": self.tag_blacklist,
            "min_file_size": self.min_file_size,
            "screen_orientation": self.screen_orientation,
            "sort_by": self.sort_by,
            "max_count": self.max_count,
            "concurrency": self.concurrency,
            "vip_only": self.vip_only,
            "use_proxy": self.use_proxy,
            "strict_original": self.strict_original,
        }


class FilterEngine:
    """壁纸筛选引擎"""

    def __init__(self, config: FilterConfig):
        self.config = config

    def match(self, wallpaper: dict) -> tuple[bool, str]:
        """
        判断一条壁纸元数据是否符合筛选规则

        Args:
            wallpaper: 来自 crawler 的壁纸字典

        Returns:
            (passed, reason)
            passed: True = 通过筛选
            reason: 未通过时的原因说明
        """
        cfg = self.config

        # 1. 壁纸类型
        if cfg.wallpaper_type != "all":
            wtype = wallpaper.get("wallpaper_type", "static")
            if wtype != cfg.wallpaper_type:
                return False, f"类型不符: {wtype} != {cfg.wallpaper_type}"

        # 2. 分类白名单
        #    支持两种形态：UUID 精确匹配（新格式）或名称/标签字符串模糊匹配（旧格式向后兼容）
        if cfg.categories:
            type_id       = wallpaper.get("type_id") or ""
            category      = (wallpaper.get("category_name") or wallpaper.get("category") or "").lower()
            tags_str      = (wallpaper.get("tags") or "").lower()
            matched = any(
                c == type_id                  # UUID 精确匹配（新格式）
                or c.lower() in category      # 中文名称匹配（如"动漫"）
                or c.lower() in tags_str      # 标签模糊匹配（旧格式兼容）
                for c in cfg.categories
            )
            if not matched:
                display = category or type_id
                return False, f"分类不在白名单: {display}"

        # 3. 分辨率
        width = wallpaper.get("width")
        height = wallpaper.get("height")

        if width is not None:
            if cfg.min_width and width < cfg.min_width:
                return False, f"宽度不足: {width} < {cfg.min_width}"
            if cfg.max_width and width > cfg.max_width:
                return False, f"宽度超限: {width} > {cfg.max_width}"

        if height is not None:
            if cfg.min_height and height < cfg.min_height:
                return False, f"高度不足: {height} < {cfg.min_height}"
            if cfg.max_height and height > cfg.max_height:
                return False, f"高度超限: {height} > {cfg.max_height}"

        # 4. 色系
        #    支持 UUID 精确匹配（新格式）或名称字符串匹配（旧格式兼容）
        if cfg.color_themes:
            color_id   = wallpaper.get("color_id") or ""
            color_name = (wallpaper.get("color_name") or wallpaper.get("color_theme") or "").lower()
            matched = any(
                c == color_id              # UUID 精确匹配
                or c.lower() == color_name # 名称匹配（如"偏蓝"）
                for c in cfg.color_themes
            )
            if not matched:
                return False, f"色系不符: {color_name or color_id}"

        # 5. 热度分
        if cfg.min_hot_score > 0:
            score = wallpaper.get("hot_score") or 0
            if score < cfg.min_hot_score:
                return False, f"热度不足: {score} < {cfg.min_hot_score}"

        # 6. 标签黑名单
        if cfg.tag_blacklist:
            tags_str = (wallpaper.get("tags") or "").lower()
            title_str = (wallpaper.get("title") or "").lower()
            for bad_tag in cfg.tag_blacklist:
                if bad_tag.lower() in tags_str or bad_tag.lower() in title_str:
                    return False, f"含黑名单标签: {bad_tag}"

        # 7. 屏幕方向（横屏=电脑，竖屏=手机）
        if cfg.screen_orientation != "all":
            w = wallpaper.get("width")
            h = wallpaper.get("height")
            if w is not None and h is not None and w > 0 and h > 0:
                is_landscape = w >= h
                if cfg.screen_orientation == "landscape" and not is_landscape:
                    return False, f"方向不符: {w}×{h} 非横屏"
                if cfg.screen_orientation == "portrait" and is_landscape:
                    return False, f"方向不符: {w}×{h} 非竖屏"

        return True, "通过"

    def filter_batch(self, wallpapers: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        批量筛选

        Returns:
            (passed_list, rejected_list)
        """
        passed, rejected = [], []
        for w in wallpapers:
            ok, reason = self.match(w)
            if ok:
                passed.append(w)
            else:
                rejected.append({**w, "_reject_reason": reason})

        logger.debug(
            f"[Filter] 筛选结果: {len(passed)} 通过 / {len(rejected)} 过滤"
        )
        return passed, rejected
