"""
Cookie 导入、存储与会话检测。
"""

from __future__ import annotations

import logging
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from backend.config import load_config
from backend.core.site_auth import extract_token
from backend.core.site_auth import probe_login_status
from backend.models.account import Account

logger = logging.getLogger(__name__)

# 心跳检测间隔（秒）
HEARTBEAT_INTERVAL = 60 * 30  # 30 分钟


class SessionManager:
    """账号会话管理器。"""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _resolve_daily_limit(account_type: str) -> int:
        if account_type == "vip":
            return 0
        cfg = load_config()
        return int(cfg.get("free_daily_limit", 10) or 10)

    def add_account(
        self,
        cookie: str,
        nickname: str = "未命名账号",
        account_type: str = "free",
    ) -> Account:
        """将用户粘贴的 cookie 字符串存入数据库。"""
        cookie = self._normalize_cookie(cookie)
        if not cookie:
            raise ValueError("Cookie 不能为空")
        self._validate_cookie(cookie)

        expires_at = self._parse_cookie_expiry(cookie)
        nickname = (nickname or "").strip() or self._extract_username(cookie) or "未命名账号"

        existing = self.db.query(Account).filter(Account.cookie == cookie).first()
        if existing:
            logger.warning(f"[Session] Cookie 已存在，更新账号 id={existing.id}")
            existing.nickname = nickname
            existing.account_type = account_type
            existing.daily_limit = self._resolve_daily_limit(account_type)
            existing.is_active = True
            existing.is_banned = False
            existing.cookie_expires_at = expires_at
            existing.daily_used = 0
            self.db.commit()
            return existing

        account = Account(
            nickname=nickname,
            cookie=cookie,
            account_type=account_type,
            daily_limit=self._resolve_daily_limit(account_type),
            cookie_expires_at=expires_at,
            is_active=True,
        )
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        logger.info(f"[Session] 添加账号 id={account.id} nickname={nickname!r} type={account_type}")
        return account

    async def check_session(self, account: Account) -> bool:
        """
        检测账号 cookie 是否仍然有效。

        使用站点真实需登录接口探测，避免前端壳页误判。
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                valid, msg = await probe_login_status(client, account.cookie)

            if valid is False:
                logger.warning(f"[Session] 账号 {account.id} 登录态失效: {msg}")
                return False
            if valid is True:
                return True

            logger.warning(f"[Session] 账号 {account.id} 登录态未知，保守认为有效: {msg}")
            return True

        except httpx.TimeoutException:
            logger.warning(f"[Session] 账号 {account.id} 检测超时，保守认为有效")
            return True
        except Exception as exc:
            logger.error(f"[Session] 账号 {account.id} 检测异常: {exc}，保守认为有效")
            return True

    async def check_all_sessions(self) -> dict[int, bool]:
        """批量检测所有未封禁账号的会话状态。"""
        accounts = (
            self.db.query(Account)
            .filter(Account.is_banned == False)  # noqa: E712
            .all()
        )
        results = {}
        for account in accounts:
            valid = await self.check_session(account)
            results[account.id] = valid
            account.is_active = valid
            self.db.commit()
            if not valid:
                logger.info(f"[Session] 账号 {account.id}({account.nickname!r}) 会话已过期，已标记为非活跃")
        return results

    def refresh_cookie(self, account_id: int, new_cookie: str) -> Optional[Account]:
        """用新 cookie 更新指定账号，并重置活跃状态。"""
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            logger.error(f"[Session] 账号 id={account_id} 不存在")
            return None

        normalized_cookie = self._normalize_cookie(new_cookie)
        self._validate_cookie(normalized_cookie)
        account.cookie = normalized_cookie
        account.is_active = True
        account.is_banned = False
        account.cookie_expires_at = self._parse_cookie_expiry(normalized_cookie)
        account.daily_used = 0
        account.last_active = datetime.now()
        self.db.commit()
        self.db.refresh(account)
        logger.info(f"[Session] 账号 {account_id} cookie 已更新")
        return account

    def get_valid_cookie(self, account_id: int) -> Optional[str]:
        """获取指定账号的 cookie；账号不可用时返回 None。"""
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account or not account.is_available:
            return None
        return account.cookie

    @staticmethod
    def _parse_cookie_expiry(cookie: str) -> Optional[datetime]:
        """
        尝试从 cookie 字符串解析过期时间。
        找不到明确过期时间时，默认 30 天后过期。
        """
        match = re.search(r"expires=([^;]+)", cookie, re.IGNORECASE)
        if match:
            try:
                from email.utils import parsedate_to_datetime

                return parsedate_to_datetime(match.group(1).strip())
            except Exception:
                pass

        return datetime.now() + timedelta(days=30)

    @staticmethod
    def _normalize_cookie(cookie: str) -> str:
        """
        规范化 cookie 字符串，统一使用 '; ' 作为分隔符。
        """
        cookie = cookie.strip()
        if not cookie:
            return cookie

        parts = re.split(r"[;,]\s*", cookie)
        valid = [part.strip() for part in parts if part.strip() and "=" in part]
        return "; ".join(valid)

    @staticmethod
    def _extract_username(cookie: str) -> Optional[str]:
        match = re.search(r"userData=([^;,]+)", cookie or "")
        if not match:
            return None

        try:
            payload = urllib.parse.unquote(match.group(1).strip())
            user_data = json.loads(payload)
        except Exception:
            return None

        user_name = str(user_data.get("userName") or "").strip()
        return user_name or None

    @staticmethod
    def _validate_cookie(cookie: str) -> None:
        parts = {}
        for part in cookie.split("; "):
            if "=" in part:
                key, value = part.split("=", 1)
                parts[key.strip()] = value.strip()

        missing = [key for key in ("userData", "server_name_session") if not parts.get(key)]
        if missing:
            raise ValueError(f"Cookie 缺少必要字段: {', '.join(missing)}")

        if not extract_token(cookie):
            raise ValueError("userData 中缺少 token，无法用于站点鉴权")

    @staticmethod
    def extract_cookie_from_headers(set_cookie_headers: list[str]) -> str:
        """从 Set-Cookie 响应头中提取请求头可用的 cookie 字符串。"""
        pairs = []
        for header in set_cookie_headers:
            key_value = header.split(";")[0].strip()
            if "=" in key_value:
                pairs.append(key_value)
        return "; ".join(pairs)
