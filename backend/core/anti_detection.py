"""
anti_detection.py — 代理池 + UA 轮换 + 请求限速

功能：
  1. 随机选择代理（支持 HTTP/SOCKS5）
  2. UA 池随机轮换
  3. 请求间隔随机延迟，模拟人工操作节奏
  4. 提供统一的 httpx.AsyncClient 工厂方法
"""

import asyncio
import hashlib
import json
import logging
import os
import random
from contextlib import asynccontextmanager
from datetime import date
from typing import AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)

# User-Agent 池（Chrome + Edge 主流版本）
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# 默认请求延迟范围（秒）
DEFAULT_MIN_DELAY = 0.5
DEFAULT_MAX_DELAY = 2.0


class AntiDetection:
    """请求反检测工具集"""

    def __init__(
        self,
        proxies: Optional[list[str]] = None,
        min_delay: float = DEFAULT_MIN_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        use_proxy: bool = True,
    ):
        """
        Args:
            proxies:    代理列表，格式如 ["http://127.0.0.1:7890", "socks5://..."]
            min_delay:  最小请求间隔（秒）
            max_delay:  最大请求间隔（秒）
            use_proxy:  是否启用代理
        """
        self.proxies = proxies or []
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.use_proxy = use_proxy
        self._proxy_failures: dict[str, int] = {}  # 代理失败计数

    # ------------------------------------------------------------------ #
    #  httpx.AsyncClient 工厂
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def build_client(
        self,
        cookie: str,
        timeout: int = 30,
    ) -> AsyncIterator[httpx.AsyncClient]:
        """
        构建带代理和 UA 的 httpx.AsyncClient 上下文管理器

        用法：
            async with anti.build_client(cookie) as client:
                resp = await client.get(url)
        """
        proxy = self._pick_proxy() if self.use_proxy and self.proxies else None

        client_kwargs = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(timeout),
            "headers": self.build_headers(cookie),
        }
        if proxy:
            client_kwargs["proxy"] = proxy

        async with httpx.AsyncClient(**client_kwargs) as client:
            yield client

    # ------------------------------------------------------------------ #
    #  请求头构建
    # ------------------------------------------------------------------ #

    def build_headers(
        self,
        cookie: str,
        referer: str = "https://haowallpaper.com/",
        extra: Optional[dict] = None,
    ) -> dict:
        """构建模拟浏览器的请求头"""
        headers = {
            "Cookie": cookie,
            "User-Agent": self._pick_ua(),
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------ #
    #  延迟控制
    # ------------------------------------------------------------------ #

    async def random_delay(
        self,
        min_s: Optional[float] = None,
        max_s: Optional[float] = None,
    ) -> None:
        """随机等待，模拟人工操作间隔"""
        lo = min_s if min_s is not None else self.min_delay
        hi = max_s if max_s is not None else self.max_delay
        delay = random.uniform(lo, hi)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------ #
    #  代理管理
    # ------------------------------------------------------------------ #

    def add_proxy(self, proxy: str) -> None:
        """动态添加代理"""
        if proxy not in self.proxies:
            self.proxies.append(proxy)
            logger.info(f"[Anti] 添加代理: {proxy}")

    def remove_proxy(self, proxy: str) -> None:
        """移除代理"""
        if proxy in self.proxies:
            self.proxies.remove(proxy)
            self._proxy_failures.pop(proxy, None)
            logger.info(f"[Anti] 移除代理: {proxy}")

    def report_proxy_failure(self, proxy: str) -> None:
        """报告代理失败，失败 3 次后自动移除"""
        self._proxy_failures[proxy] = self._proxy_failures.get(proxy, 0) + 1
        if self._proxy_failures[proxy] >= 3:
            logger.warning(f"[Anti] 代理 {proxy} 连续失败 3 次，自动移除")
            self.remove_proxy(proxy)

    def get_proxy_health(self) -> list[dict]:
        """返回代理健康状态列表"""
        return [
            {
                "proxy": p,
                "failures": self._proxy_failures.get(p, 0),
                "healthy": self._proxy_failures.get(p, 0) < 3,
            }
            for p in self.proxies
        ]

    # ------------------------------------------------------------------ #
    #  内部工具
    # ------------------------------------------------------------------ #

    def _pick_ua(self) -> str:
        """随机选择 User-Agent"""
        return random.choice(USER_AGENTS)

    def _pick_proxy(self) -> Optional[str]:
        """随机选择一个健康代理"""
        healthy = [
            p for p in self.proxies
            if self._proxy_failures.get(p, 0) < 3
        ]
        return random.choice(healthy) if healthy else None


# ─────────────────────────────────────────────────────────────────────────────
#  HumanBehaviorController — 模拟人类下载节奏，防止 VIP 账号被封禁
# ─────────────────────────────────────────────────────────────────────────────

class HumanBehaviorController:
    """
    模拟人类下载行为，防止 VIP 账号因自动化特征触发风控封禁。

    核心机制
    ─────────
    1. 每日随机上限
       基于「日期字符串 MD5 哈希」生成 [DAILY_MIN, DAILY_MAX] 内的整数，
       同一天内多次重启结果完全一致，持久化到 data/human_behavior.json。

    2. 下载节奏（三层延迟）
       层 1 — 基础浏览延迟（每张必有）：3–10 秒
               模拟人看图 / 考虑是否下载的停留时间。
       层 2 — 批次疲劳休息（每 8–15 张触发一次）：60–180 秒
               触发阈值随已下载数动态变化，避免固定周期被识别。
       层 3 — 随机长休息（约 3% 概率）：5–15 分钟
               模拟用户中途离开去做其他事情。

    使用方式
    ─────────
    # 在 _execute_task 开头检查每日上限：
    if human_ctrl.is_daily_limit_reached():
        return  # 今日不再下载

    # 每次成功下载后调用（在 pool.release 之后）：
    human_ctrl.record_download()
    await human_ctrl.post_download_delay(task.success_count)
    """

    DAILY_MIN = 25   # 每日下载上限的下界
    DAILY_MAX = 70   # 每日下载上限的上界

    def __init__(self, data_dir: str = "data"):
        self._state_file = os.path.join(data_dir, "human_behavior.json")
        self._state: dict = {}
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, "r", encoding="utf-8") as f:
                    self._state = json.load(f)
        except Exception:
            self._state = {}

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._state_file)), exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[Human] 状态保存失败: %s", exc)

    # ── 每日上限 ─────────────────────────────────────────────────────────────

    def _ensure_today(self) -> dict:
        """确保 _state 对应今天，否则重新生成当天的随机上限。"""
        today = date.today().isoformat()
        if self._state.get("date") != today:
            # 哈希种子：同一天结果稳定，不同天差异足够大
            seed = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
            rng = random.Random(seed)
            # 正态分布截断到 [DAILY_MIN, DAILY_MAX]，均值 45，标准差 12
            raw = rng.gauss(45, 12)
            limit = max(self.DAILY_MIN, min(self.DAILY_MAX, int(raw)))
            self._state = {"date": today, "daily_limit": limit, "downloaded": 0}
            self._save()
            logger.info("[Human] 新的一天，今日下载上限: %d 张", limit)
        return self._state

    @property
    def daily_limit(self) -> int:
        """今日下载上限（每天不同，同一天稳定，重启不变）"""
        return self._ensure_today()["daily_limit"]

    @property
    def downloaded_today(self) -> int:
        """今日已成功记录的下载数"""
        return self._ensure_today().get("downloaded", 0)

    @property
    def remaining_today(self) -> int:
        """今日剩余可下载数"""
        return max(0, self.daily_limit - self.downloaded_today)

    def is_daily_limit_reached(self) -> bool:
        """今日是否已达上限"""
        return self.downloaded_today >= self.daily_limit

    def record_download(self) -> None:
        """记录一次成功下载（asyncio 单线程安全，无 await）"""
        state = self._ensure_today()
        state["downloaded"] = state.get("downloaded", 0) + 1
        self._save()

    # ── 节奏控制 ─────────────────────────────────────────────────────────────

    async def post_download_delay(self, success_count: int) -> None:
        """
        每次成功下载后的等待，模拟人查看壁纸的行为节奏。

        Args:
            success_count: 当前任务已成功下载的总数（用于触发批次休息）
        """
        # 层 1：基础浏览延迟（每张必有）
        base = random.uniform(3.0, 10.0)
        await asyncio.sleep(base)

        # 层 2：批次疲劳休息
        # 触发阈值在 8–15 之间随 success_count 动态变化，避免固定周期
        burst_size = 8 + (success_count % 8)  # 8 ~ 15
        if success_count > 0 and success_count % burst_size == 0:
            rest = random.uniform(60.0, 180.0)
            logger.info("[Human] 已下载 %d 张，批次休息 %.0f 秒", success_count, rest)
            await asyncio.sleep(rest)
            return  # 已经有长休息，不再叠加层 3

        # 层 3：随机长休息（~3% 概率，模拟用户去做其他事）
        if random.random() < 0.03:
            rest = random.uniform(300.0, 900.0)
            logger.info("[Human] 随机长休息 %.0f 秒（模拟用户离开）", rest)
            await asyncio.sleep(rest)
