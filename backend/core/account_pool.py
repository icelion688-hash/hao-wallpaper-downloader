"""
account_pool.py — 账号轮询 + 配额控制 + 每日重置

调度策略：
  1. 优先使用 VIP 账号（无次数限制）
  2. VIP 不存在/不可用时，从免费账号池中选 daily_used < daily_limit 的
  3. 所有免费账号配额用尽时，等待次日凌晨重置
  4. 每次下载后自动扣减配额
"""

import asyncio
import logging
from datetime import datetime, time as dt_time
from typing import Optional

from sqlalchemy.orm import Session

from backend.models.account import Account

logger = logging.getLogger(__name__)


class AccountPool:
    """账号池调度器"""

    def __init__(self, db: Session, vip_only: bool = False):
        """
        Args:
            db:       数据库会话
            vip_only: 为 True 时仅使用 VIP 账号
        """
        self.db = db
        self.vip_only = vip_only
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    #  核心接口：获取下一个可用账号
    # ------------------------------------------------------------------ #

    async def acquire(self) -> Optional[Account]:
        """
        获取一个可用账号（线程安全）

        Returns:
            可用的 Account 对象，或 None（无可用账号）
        """
        async with self._lock:
            self._reset_daily_quota_if_needed()

            account = self._pick_vip_account()
            if account:
                logger.debug(f"[Pool] 使用 VIP 账号 id={account.id} ({account.nickname!r})")
                return account

            if self.vip_only:
                logger.warning("[Pool] 仅VIP模式：无可用 VIP 账号")
                return None

            account = self._pick_free_account()
            if account:
                logger.debug(
                    f"[Pool] 使用免费账号 id={account.id} ({account.nickname!r}) "
                    f"今日已用 {account.daily_used}/{account.daily_limit}"
                )
                return account

            logger.warning("[Pool] 所有账号配额已耗尽，今日无可用账号")
            return None

    async def release(self, account: Account, success: bool = True, consume_quota: bool = True):
        """
        归还账号，更新活跃时间，可选是否扣减配额。

        Args:
            account:       使用的账号
            success:       是否操作成功（保留参数，供未来差异化处理）
            consume_quota: 是否扣减配额（爬取列表不扣，仅实际下载才扣）
        """
        async with self._lock:
            # 重新从 DB 获取最新状态（避免并发写冲突）
            fresh = self.db.query(Account).filter(Account.id == account.id).first()
            if not fresh:
                return

            if consume_quota and fresh.account_type == "free":
                fresh.daily_used = (fresh.daily_used or 0) + 1
                logger.debug(
                    f"[Pool] 账号 {fresh.id} 配额 {fresh.daily_used}/{fresh.daily_limit}"
                )

            fresh.last_active = datetime.now()
            self.db.commit()

    async def mark_banned(self, account: Account, reason: str = ""):
        """将账号标记为封禁状态（收到 403/被封禁响应时调用）"""
        async with self._lock:
            fresh = self.db.query(Account).filter(Account.id == account.id).first()
            if fresh:
                fresh.is_banned = True
                fresh.is_active = False
                self.db.commit()
                logger.warning(
                    f"[Pool] 账号 {fresh.id}({fresh.nickname!r}) 已标记为封禁. 原因: {reason}"
                )

    # ------------------------------------------------------------------ #
    #  查询接口
    # ------------------------------------------------------------------ #

    def get_all_accounts(self) -> list[Account]:
        """获取所有账号列表（含停用/封禁账号）"""
        return self.db.query(Account).order_by(Account.id).all()

    def get_available_accounts(self) -> list[Account]:
        """获取当前所有可用账号"""
        self._reset_daily_quota_if_needed()
        return [a for a in self.get_all_accounts() if a.is_available]

    def get_pool_status(self) -> dict:
        """返回账号池状态摘要"""
        accounts = self.get_all_accounts()
        vip_list = [a for a in accounts if a.account_type == "vip"]
        free_list = [a for a in accounts if a.account_type == "free"]

        return {
            "total": len(accounts),
            "vip_total": len(vip_list),
            "vip_available": sum(1 for a in vip_list if a.is_available),
            "free_total": len(free_list),
            "free_available": sum(1 for a in free_list if a.is_available),
            "free_quota_remaining": sum(
                a.remaining_quota for a in free_list if a.is_available
            ),
            "banned_count": sum(1 for a in accounts if a.is_banned),
        }

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #

    def _pick_vip_account(self) -> Optional[Account]:
        """按 last_active 升序选最久未使用的 VIP 账号（负载均衡）"""
        return (
            self.db.query(Account)
            .filter(
                Account.account_type == "vip",
                Account.is_active == True,   # noqa: E712
                Account.is_banned == False,  # noqa: E712
            )
            .order_by(Account.last_active.asc().nullsfirst())
            .first()
        )

    def _pick_free_account(self) -> Optional[Account]:
        """选 daily_used 最少的免费账号（均衡消耗配额）"""
        return (
            self.db.query(Account)
            .filter(
                Account.account_type == "free",
                Account.is_active == True,    # noqa: E712
                Account.is_banned == False,   # noqa: E712
                Account.daily_used < Account.daily_limit,
            )
            .order_by(Account.daily_used.asc())
            .first()
        )

    def _reset_daily_quota_if_needed(self):
        """
        检查是否需要重置免费账号的每日配额
        重置条件：daily_reset_at 为 None 或早于今天凌晨
        """
        today_midnight = datetime.combine(datetime.today(), dt_time.min)

        accounts_to_reset = (
            self.db.query(Account)
            .filter(
                Account.account_type == "free",
                (Account.daily_reset_at == None)  # noqa: E711
                | (Account.daily_reset_at < today_midnight),
            )
            .all()
        )

        if accounts_to_reset:
            count = len(accounts_to_reset)
            for account in accounts_to_reset:
                account.daily_used = 0
                account.daily_reset_at = today_midnight
            self.db.commit()
            logger.info(f"[Pool] 已重置 {count} 个免费账号的每日配额")

    # ------------------------------------------------------------------ #
    #  配额重置后台任务（可在 main.py 中以 asyncio.create_task 启动）
    # ------------------------------------------------------------------ #

    async def daily_reset_loop(self):
        """每小时检查一次是否需要重置配额（用于后台常驻任务）"""
        while True:
            try:
                self._reset_daily_quota_if_needed()
            except Exception as e:
                logger.error(f"[Pool] 每日重置检查异常: {e}")
            await asyncio.sleep(3600)  # 1 小时检查一次
