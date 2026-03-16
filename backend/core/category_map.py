"""
category_map.py — 分类 / 色系静态映射表

数据来源：haowallpaper.com /link/pc/wallpaper/getTypeAll API（MCP 实测，2026-03-15）
  - key "1"：壁纸分类（typeId → name/code）
  - key "3"：色系（colorId → name/hex）
  - key "2"：分辨率档位（1K–33K，可按需扩展）
"""

# ── 分类映射：typeId（UUID）→ {name, code} ──────────────────────────────────
CATEGORY_MAP: dict[str, dict] = {
    "35c203f75643ac7803b8f706fa91ef40": {"name": "魅力｜迷人",  "code": "魅力四溢"},
    "ea0a4b100d440b83f2feec8abbd3d9e1": {"name": "自制｜艺术",  "code": "自制/艺术"},
    "760943d7b1ac898ff9eb31900cbf5df7": {"name": "安逸｜自由",  "code": "安逸/自由"},
    "55bcd42f60c4631af0a90bacec892958": {"name": "科幻｜星云",  "code": "科幻/星云"},
    "553dff627434cc5683a776216c6045d2": {"name": "动漫｜二次元", "code": "Anime"},
    "0202b9e54c3e843a4e70dc0150399d11": {"name": "自然｜风景",  "code": "风景"},
    "15ea11c65ce0d00c1e4bf042a66dbe15": {"name": "游戏｜玩具",  "code": "游戏/玩具"},
    "25e2d674a895d54b467a9e4820a12e04": {"name": "程序｜代码",  "code": "程序"},
    "ef9afbc2abbafdb6c414df491842c735": {"name": "未定义",      "code": "General"},
}

# ── 色系映射：colorId（UUID）→ {name, hex} ─────────────────────────────────
COLOR_MAP: dict[str, dict] = {
    "df3121699fcf4155c35ae50b7c93b3f1": {"name": "偏蓝",    "hex": "#1C8DB5"},
    "4b119907ec429a185de5fce6f580036e": {"name": "偏绿",    "hex": "#318929"},
    "42a0ba70ffd32f479bb79154922a9f66": {"name": "偏红",    "hex": "#6C1B1B"},
    "34d651609d3e8000066a0397cd8902d0": {"name": "灰/白",   "hex": "#aeaeae"},
    "e35f3c31339fa77498d682ff54ba5069": {"name": "紫/粉",   "hex": "#9f2fc4"},
    "b6f2e7a3e9aaf1eab391c01b0fed404a": {"name": "暗色",    "hex": "#303030"},
    "5f45dad428890099e26979f6f28e9c0b": {"name": "偏黄",    "hex": "#C2A72D"},
    "24d7ef760ecca54da7e59735e66dad94": {"name": "其他颜色", "hex": "#888888"},
}


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def get_category_name(type_id: str) -> str:
    """根据 typeId UUID 获取分类显示名称，未知 ID 返回空字符串"""
    return CATEGORY_MAP.get(type_id, {}).get("name", "")


def get_color_name(color_id: str) -> str:
    """根据 colorId UUID 获取色系显示名称"""
    return COLOR_MAP.get(color_id, {}).get("name", "")


def get_color_hex(color_id: str) -> str:
    """根据 colorId UUID 获取色系 CSS 十六进制颜色值"""
    return COLOR_MAP.get(color_id, {}).get("hex", "")


def list_categories() -> list[dict]:
    """返回所有分类列表（含 id/name/code）"""
    return [{"id": k, "name": v["name"], "code": v["code"]} for k, v in CATEGORY_MAP.items()]


def list_colors() -> list[dict]:
    """返回所有色系列表（含 id/name/hex）"""
    return [{"id": k, "name": v["name"], "hex": v["hex"]} for k, v in COLOR_MAP.items()]
