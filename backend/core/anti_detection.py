"""
anti_detection.py — 代理池 + 浏览器指纹一致性 + 请求限速

功能：
  1. 随机选择代理（支持 HTTP/SOCKS5）
  2. 浏览器 Session Profile —— 同一任务内 UA / sec-ch-ua / 平台 / 语言保持一致
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
from datetime import date, datetime
from typing import AsyncIterator, Optional


import httpx

logger = logging.getLogger(__name__)

# ── 浏览器 Session Profile 池 ──────────────────────────────────────────────────
# 每个 profile 内所有字段保持真实浏览器的一致性：
# UA 版本、sec-ch-ua 品牌、sec-ch-ua-platform、Accept-Language 全部匹配。
# 任务开始时选定一个 profile，整个任务期间不再切换，避免同会话内 UA 跳变被检测。
_BROWSER_PROFILES = [
    # Chrome 130 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    },
    # Chrome 131 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en;q=0.8",
    },
    # Chrome 132 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    },
    # Chrome 133 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en;q=0.8",
    },
    # Chrome 131 / macOS
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"macOS"',
        "accept_lang": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    },
    # Chrome 132 / macOS
    {
        "ua": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        "sec_ch_ua_platform": '"macOS"',
        "accept_lang": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    },
    # Edge 131 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
        "sec_ch_ua": '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en;q=0.8",
    },
    # Edge 132 / Windows
    {
        "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0",
        "sec_ch_ua": '"Not A(Brand";v="8", "Chromium";v="132", "Microsoft Edge";v="132"',
        "sec_ch_ua_platform": '"Windows"',
        "accept_lang": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    },
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
    #  Session Profile（任务级浏览器指纹一致性）
    # ------------------------------------------------------------------ #

    @staticmethod
    def pick_session_profile() -> dict:
        """
        为一个下载任务选定一个浏览器 Session Profile。

        同一任务内所有请求（列表/详情/下载/altcha）均使用同一 profile，
        确保 UA / sec-ch-ua / 平台信息在整个会话中保持一致，
        避免因 UA 跳变触发 WAF 行为分析规则。

        Returns:
            profile dict，包含 ua / sec_ch_ua / sec_ch_ua_platform / accept_lang
        """
        return random.choice(_BROWSER_PROFILES)

    # ------------------------------------------------------------------ #
    #  httpx.AsyncClient 工厂
    # ------------------------------------------------------------------ #

    @asynccontextmanager
    async def build_client(
        self,
        cookie: str,
        timeout: int = 30,
        profile: Optional[dict] = None,
    ) -> AsyncIterator[httpx.AsyncClient]:
        """
        构建带代理和 UA 的 httpx.AsyncClient 上下文管理器

        Args:
            cookie:  账号 cookie
            timeout: 超时秒数
            profile: Session Profile（None 时随机选一个）
        """
        proxy = self._pick_proxy() if self.use_proxy and self.proxies else None
        _profile = profile or self.pick_session_profile()

        client_kwargs = {
            "follow_redirects": True,
            "timeout": httpx.Timeout(timeout),
            "headers": self.build_headers(cookie, profile=_profile),
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
        profile: Optional[dict] = None,
    ) -> dict:
        """
        构建模拟浏览器的请求头。

        Args:
            cookie:  账号 cookie
            referer: Referer 地址
            extra:   额外请求头（会覆盖默认值）
            profile: Session Profile；None 时从池中随机选一个。
                     对于同一任务应传入同一 profile，保持会话一致性。
        """
        _profile = profile or self.pick_session_profile()
        headers = {
            "Cookie": cookie,
            "User-Agent": _profile["ua"],
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": _profile["accept_lang"],
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "sec-ch-ua": _profile["sec_ch_ua"],
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": _profile["sec_ch_ua_platform"],
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
        """随机等待，模拟人工操作间隔（页面翻页等场景）"""
        lo = min_s if min_s is not None else self.min_delay
        hi = max_s if max_s is not None else self.max_delay
        delay = random.uniform(lo, hi)
        await asyncio.sleep(delay)

    async def pre_request_delay(
        self,
        min_s: float = 0.2,
        max_s: float = 0.9,
    ) -> None:
        """
        API 调用前的轻量延迟，模拟浏览器渲染/JS 处理耗时。

        适用于 getCompleteUrl、altcha verify 等关键 API 调用前，
        避免请求时序过于精确（毫秒级触发）被 WAF 检测为自动化行为。
        """
        delay = random.uniform(min_s, max_s)
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

    2. 下载节奏（四层延迟）
       层 1 — 基础浏览延迟（每张必有）：
               活跃时段(8-23点) 3–8 秒，非活跃时段 5–15 秒
               模拟人看图 / 考虑是否下载的停留时间。
       层 2 — 批次疲劳休息（每 8–15 张触发一次）：60–180 秒
               触发阈值随已下载数动态变化，避免固定周期被识别。
       层 3 — 随机长休息（约 3% 概率）：5–15 分钟
               模拟用户中途离开去做其他事情。
       层 4 — 会话结束模拟（满 10 张后约 5% 概率）：20–90 分钟
               模拟用户关闭浏览器、离开较长时间后再回来。
               触发后记录日志，调用方应暂停本轮任务。

    3. 活跃时段感知
       is_active_hour() 在 08:00–23:00 返回 True，
       非活跃时段自动加长层 1 延迟（模拟深夜偶尔浏览节奏）。
    """

    DAILY_MIN = 25   # 每日下载上限的下界
    DAILY_MAX = 70   # 每日下载上限的上界
    MANUAL_LIMIT_MIN = 1
    MANUAL_LIMIT_MAX = 500

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
        if not isinstance(self._state, dict):
            self._state = {}
        self._state["limit_mode"] = self._normalize_limit_mode(
            self._state.get("limit_mode", "auto")
        )
        self._state["manual_limit"] = self._normalize_manual_limit(
            self._state.get("manual_limit")
        )

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._state_file)), exist_ok=True)
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("[Human] 状态保存失败: %s", exc)

    @staticmethod
    def _normalize_limit_mode(raw_mode: str) -> str:
        return "manual" if str(raw_mode).strip().lower() == "manual" else "auto"

    @classmethod
    def _normalize_manual_limit(cls, raw_limit) -> Optional[int]:
        if raw_limit in (None, "", 0, "0"):
            return None
        try:
            manual_limit = int(raw_limit)
        except (TypeError, ValueError):
            return None
        return max(cls.MANUAL_LIMIT_MIN, min(cls.MANUAL_LIMIT_MAX, manual_limit))

    @classmethod
    def _auto_limit_for_date(cls, date_str: str) -> int:
        # 哈希种子：同一天结果稳定，不同天差异足够大
        seed = int(hashlib.md5(date_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        # 正态分布截断到 [DAILY_MIN, DAILY_MAX]，均值 45，标准差 12
        raw = rng.gauss(45, 12)
        return max(cls.DAILY_MIN, min(cls.DAILY_MAX, int(raw)))

    def _resolve_limit_for_day(
        self,
        date_str: str,
        limit_mode: Optional[str] = None,
        manual_limit: Optional[int] = None,
    ) -> int:
        mode = self._normalize_limit_mode(limit_mode or self._state.get("limit_mode", "auto"))
        resolved_manual_limit = self._normalize_manual_limit(
            manual_limit if manual_limit is not None else self._state.get("manual_limit")
        )
        if mode == "manual" and resolved_manual_limit is not None:
            return resolved_manual_limit
        return self._auto_limit_for_date(date_str)

    def apply_daily_limit_config(
        self,
        limit_mode: str = "auto",
        manual_limit: Optional[int] = None,
    ) -> None:
        normalized_mode = self._normalize_limit_mode(limit_mode)
        normalized_manual_limit = self._normalize_manual_limit(manual_limit)
        today = date.today().isoformat()
        downloaded = max(0, int(self._state.get("downloaded", 0) or 0))
        effective_limit = self._resolve_limit_for_day(
            today,
            limit_mode=normalized_mode,
            manual_limit=normalized_manual_limit,
        )
        changed = (
            self._state.get("limit_mode") != normalized_mode
            or self._state.get("manual_limit") != normalized_manual_limit
            or self._state.get("date") != today
            or self._state.get("daily_limit") != effective_limit
        )
        self._state.update(
            {
                "date": today,
                "limit_mode": normalized_mode,
                "manual_limit": normalized_manual_limit,
                "daily_limit": effective_limit,
                "downloaded": downloaded if self._state.get("date") == today else 0,
            }
        )
        if changed:
            self._save()
            mode_label = "手动" if normalized_mode == "manual" and normalized_manual_limit else "自动"
            logger.info(
                "[Human] 每日上限策略已更新: %s模式，今日上限 %d 张，已下 %d 张",
                mode_label,
                effective_limit,
                self._state.get("downloaded", 0),
            )

    # ── 活跃时段感知 ─────────────────────────────────────────────────────────

    @staticmethod
    def is_active_hour(
        tz: str = "Asia/Shanghai",
        start: int = 8,
        end: int = 23,
    ) -> bool:
        """
        判断当前是否处于活跃时段（默认上海时间 08:00–23:00）。

        Args:
            tz:    时区名称，如 "Asia/Shanghai"（默认）或 "UTC"
            start: 活跃时段开始小时（含，0-23）
            end:   活跃时段结束小时（不含，0-23）；支持跨午夜，如 start=22, end=6

        活跃时段延迟较短，模拟白天正常浏览节奏；
        非活跃时段（深夜/凌晨）延迟较长，模拟偶发使用行为。
        """
        try:
            from zoneinfo import ZoneInfo
            now = datetime.now(ZoneInfo(tz))
        except Exception:
            now = datetime.now()
        hour = now.hour
        if start <= end:
            return start <= hour < end
        # 跨午夜：如 22–6 表示 22:00 到次日 05:59
        return hour >= start or hour < end

    # ── 每日上限 ─────────────────────────────────────────────────────────────

    def _ensure_today(self) -> dict:
        """确保 _state 对应今天，否则重新生成当天的随机上限。"""
        today = date.today().isoformat()
        limit_mode = self._normalize_limit_mode(self._state.get("limit_mode", "auto"))
        manual_limit = self._normalize_manual_limit(self._state.get("manual_limit"))
        limit = self._resolve_limit_for_day(today, limit_mode=limit_mode, manual_limit=manual_limit)
        if self._state.get("date") != today:
            self._state = {
                "date": today,
                "daily_limit": limit,
                "downloaded": 0,
                "limit_mode": limit_mode,
                "manual_limit": manual_limit,
            }
            self._save()
            mode_label = "手动" if limit_mode == "manual" and manual_limit else "自动"
            logger.info("[Human] 新的一天，今日下载上限: %d 张（%s模式）", limit, mode_label)
        else:
            changed = False
            if self._state.get("daily_limit") != limit:
                self._state["daily_limit"] = limit
                changed = True
            if self._state.get("limit_mode") != limit_mode:
                self._state["limit_mode"] = limit_mode
                changed = True
            if self._state.get("manual_limit") != manual_limit:
                self._state["manual_limit"] = manual_limit
                changed = True
            if changed:
                self._save()
        return self._state

    @property
    def daily_limit(self) -> int:
        """今日下载上限（每天不同，同一天稳定，重启不变）"""
        return self._ensure_today()["daily_limit"]

    @property
    def daily_limit_mode(self) -> str:
        """每日上限模式：auto / manual"""
        return self._ensure_today().get("limit_mode", "auto")

    @property
    def manual_daily_limit(self) -> Optional[int]:
        """手动模式下的用户配置上限"""
        return self._ensure_today().get("manual_limit")

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

    async def post_download_delay(self, success_count: int) -> bool:
        """
        每次成功下载后的等待，模拟人查看壁纸的行为节奏。

        Args:
            success_count: 当前任务已成功下载的总数（用于触发批次休息）

        Returns:
            True  — 正常延迟后继续
            False — 触发层 4 会话结束模拟，调用方应终止本轮任务（长时间挂起）
        """
        # 层 4：会话结束模拟（满 10 张后 5% 概率，仅在活跃时段触发）
        # 模拟用户关闭标签页、去做别的事，稍后重开的行为
        if success_count >= 10 and random.random() < 0.05:
            rest = random.uniform(20 * 60, 90 * 60)  # 20–90 分钟
            logger.info(
                "[Human] 层4-会话结束模拟，暂停 %.0f 分钟（模拟用户关闭浏览器）",
                rest / 60,
            )
            await asyncio.sleep(rest)
            return False

        # 层 2：批次疲劳休息（优先级高于层 3，触发后跳过层 1/3）
        # 触发阈值在 8–15 之间随 success_count 动态变化，避免固定周期
        burst_size = 8 + (success_count % 8)  # 8 ~ 15
        if success_count > 0 and success_count % burst_size == 0:
            rest = random.uniform(60.0, 180.0)
            logger.info("[Human] 已下载 %d 张，批次休息 %.0f 秒", success_count, rest)
            await asyncio.sleep(rest)
            return True

        # 层 3：随机长休息（~3% 概率，模拟用户去做其他事）
        if random.random() < 0.03:
            rest = random.uniform(300.0, 900.0)
            logger.info("[Human] 随机长休息 %.0f 秒（模拟用户离开）", rest)
            await asyncio.sleep(rest)
            return True

        # 层 1：基础浏览延迟（每张必有），活跃时段较短，非活跃时段较长
        # 使用上海时区判断，确保与目标网站用户时区一致
        if self.is_active_hour("Asia/Shanghai", 8, 23):
            base = random.uniform(3.0, 8.0)   # 白天：3–8 秒
        else:
            base = random.uniform(5.0, 15.0)  # 深夜：5–15 秒
        await asyncio.sleep(base)

        return True
