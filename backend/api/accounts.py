"""
账号管理 API。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import load_config
from backend.core.account_pool import AccountPool
from backend.core.anti_detection import AntiDetection
from backend.core.captcha_solver import AltchaSolver
from backend.core.session_manager import SessionManager
from backend.core.site_auth import probe_login_status, probe_original_access
from backend.models.account import Account
from backend.models.database import get_db
from backend.models.wallpaper import Wallpaper

logger = logging.getLogger(__name__)
router = APIRouter()


class AddAccountRequest(BaseModel):
    cookie: str
    nickname: str = "未命名账号"
    account_type: str = "free"


class UpdateCookieRequest(BaseModel):
    cookie: str


class UpdateQuotaRequest(BaseModel):
    daily_used: int


class UpdateAccountRequest(BaseModel):
    nickname: str
    account_type: str


class BatchVerifyRequest(BaseModel):
    account_ids: list[int]


class BatchUpdateTypeRequest(BaseModel):
    account_ids: list[int]
    account_type: str


class AccountResponse(BaseModel):
    id: int
    nickname: str
    account_type: str
    daily_used: int
    daily_limit: int
    remaining_quota: int
    is_active: bool
    is_banned: bool
    is_available: bool
    cookie_expires_at: Optional[datetime]
    last_active: Optional[datetime]
    last_verify_at: Optional[datetime]
    last_verify_status: Optional[str]
    last_verify_msg: Optional[str]
    last_verify_auth_valid: Optional[bool]
    last_verify_can_original: Optional[bool]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


def _to_response(account: Account) -> dict:
    return {
        "id": account.id,
        "nickname": account.nickname,
        "account_type": account.account_type,
        "daily_used": account.daily_used,
        "daily_limit": account.daily_limit,
        "remaining_quota": account.remaining_quota,
        "is_active": account.is_active,
        "is_banned": account.is_banned,
        "is_available": account.is_available,
        "cookie_expires_at": account.cookie_expires_at,
        "last_active": account.last_active,
        "last_verify_at": account.last_verify_at,
        "last_verify_status": account.last_verify_status,
        "last_verify_msg": account.last_verify_msg,
        "last_verify_auth_valid": account.last_verify_auth_valid,
        "last_verify_can_original": account.last_verify_can_original,
        "created_at": account.created_at,
    }


def _free_daily_limit() -> int:
    cfg = load_config()
    return int(cfg.get("free_daily_limit", 10) or 10)


def _daily_limit_for(account_type: str) -> int:
    return 0 if account_type == "vip" else _free_daily_limit()


def _normalize_daily_limits(db: Session) -> None:
    """按当前配置修正历史账号的日配额。"""
    free_limit = _free_daily_limit()
    changed = False

    for account in db.query(Account).all():
        target = 0 if account.account_type == "vip" else free_limit
        if account.daily_limit != target:
            account.daily_limit = target
            changed = True

    if changed:
        db.commit()


def _count_today_originals(account_id: int, db: Session) -> int:
    today_str = date.today().isoformat()
    return (
        db.query(func.count(Wallpaper.id))
        .filter(
            Wallpaper.account_id == account_id,
            Wallpaper.is_original == True,  # noqa: E712
            func.date(Wallpaper.downloaded_at) == today_str,
        )
        .scalar()
    ) or 0


def _get_account_or_404(account_id: int, db: Session) -> Account:
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, f"账号 {account_id} 不存在")
    return account


def _get_accounts_by_ids(account_ids: list[int], db: Session) -> list[Account]:
    normalized_ids = []
    seen = set()
    for account_id in account_ids:
        if account_id in seen:
            continue
        seen.add(account_id)
        normalized_ids.append(account_id)

    if not normalized_ids:
        raise HTTPException(400, "account_ids 不能为空")

    accounts = db.query(Account).filter(Account.id.in_(normalized_ids)).all()
    account_map = {account.id: account for account in accounts}
    missing_ids = [account_id for account_id in normalized_ids if account_id not in account_map]
    if missing_ids:
        raise HTTPException(404, f"账号不存在: {', '.join(str(item) for item in missing_ids)}")

    return [account_map[account_id] for account_id in normalized_ids]


def _save_verify_state(
    account: Account,
    *,
    status: str,
    msg: str,
    auth_valid: Optional[bool],
    can_original: Optional[bool],
) -> None:
    account.last_verify_at = datetime.now()
    account.last_verify_status = status
    account.last_verify_msg = (msg or "")[:255]
    account.last_verify_auth_valid = auth_valid
    account.last_verify_can_original = can_original


def _apply_login_probe_state(account: Account, valid: bool) -> None:
    account.is_active = valid
    _save_verify_state(
        account,
        status="login_valid" if valid else "login_invalid",
        msg="登录态有效" if valid else "登录态失效",
        auth_valid=valid,
        can_original=account.last_verify_can_original if valid else False,
    )


async def _verify_account_access(account: Account) -> dict:
    cfg = load_config()
    anti = AntiDetection(
        proxies=cfg.get("proxies", []),
        min_delay=cfg.get("min_delay", 0.5),
        max_delay=cfg.get("max_delay", 2.0),
        use_proxy=cfg.get("use_proxy", False),
    )
    session_profile = anti.pick_session_profile()
    solver = AltchaSolver()
    async with anti.build_client(account.cookie, timeout=20, profile=session_profile) as client:
        auth_valid, auth_msg = await probe_login_status(
            client,
            account.cookie,
            session_profile=session_profile,
        )
        if auth_valid is False:
            account.is_active = False
            _save_verify_state(
                account,
                status="login_invalid",
                msg=f"登录态失效: {auth_msg}",
                auth_valid=False,
                can_original=False,
            )
            return {
                "account_id": account.id,
                "auth_valid": False,
                "can_download_original": False,
                "has_quota": False,
                "daily_used": account.daily_used,
                "daily_limit": account.daily_limit,
                "website_status": 401,
                "msg": f"登录态失效: {auth_msg}",
            }

        if auth_valid is None:
            _save_verify_state(
                account,
                status="verify_unknown",
                msg=auth_msg,
                auth_valid=None,
                can_original=None,
            )
            return {
                "account_id": account.id,
                "auth_valid": None,
                "can_download_original": None,
                "has_quota": None,
                "daily_used": account.daily_used,
                "daily_limit": account.daily_limit,
                "website_status": None,
                "msg": auth_msg,
            }

        can_original, website_status, website_msg = await probe_original_access(
            client,
            account.cookie,
            solver,
            session_profile=session_profile,
        )

    account.is_active = True

    if can_original is True:
        msg = "站点授权正常，可下载原图"
        if account.account_type == "free":
            msg = "配额充足，可正常下载原图"
        _save_verify_state(
            account,
            status="original_ok",
            msg=msg,
            auth_valid=True,
            can_original=True,
        )
        return {
            "account_id": account.id,
            "auth_valid": True,
            "can_download_original": True,
            "has_quota": True,
            "daily_used": account.daily_used,
            "daily_limit": account.daily_limit,
            "website_status": website_status,
            "msg": msg,
        }

    if can_original is False:
        if account.account_type == "free" and account.daily_used < account.daily_limit:
            old_used = account.daily_used
            account.daily_used = account.daily_limit
            logger.info(
                "[Accounts] verify_quota acc=%s: 站点已拒绝原图，daily_used %s -> %s",
                account.id,
                old_used,
                account.daily_limit,
            )

        if account.account_type == "vip":
            msg = f"本地标记为 VIP，但站点原图接口拒绝访问: {website_msg}"
            status = "vip_original_denied"
        else:
            msg = f"配额已耗尽: {website_msg}"
            status = "quota_exhausted"

        _save_verify_state(
            account,
            status=status,
            msg=msg,
            auth_valid=True,
            can_original=False,
        )
        return {
            "account_id": account.id,
            "auth_valid": True,
            "can_download_original": False,
            "has_quota": False,
            "daily_used": account.daily_used,
            "daily_limit": account.daily_limit,
            "website_status": website_status,
            "msg": msg,
        }

    _save_verify_state(
        account,
        status="verify_unknown",
        msg=website_msg,
        auth_valid=True,
        can_original=None,
    )
    return {
        "account_id": account.id,
        "auth_valid": True,
        "can_download_original": None,
        "has_quota": None,
        "daily_used": account.daily_used,
        "daily_limit": account.daily_limit,
        "website_status": website_status,
        "msg": website_msg,
    }


@router.get("")
async def list_accounts(db: Session = Depends(get_db)):
    _normalize_daily_limits(db)
    accounts = db.query(Account).order_by(Account.id).all()
    return {"accounts": [_to_response(account) for account in accounts]}


@router.post("")
async def add_account(body: AddAccountRequest, db: Session = Depends(get_db)):
    if body.account_type not in ("free", "vip"):
        raise HTTPException(400, "account_type 必须是 'free' 或 'vip'")

    mgr = SessionManager(db)
    try:
        account = mgr.add_account(
            cookie=body.cookie,
            nickname=body.nickname,
            account_type=body.account_type,
        )
        return {"success": True, "account": _to_response(account)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.patch("/{account_id}")
async def update_account(account_id: int, body: UpdateAccountRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)

    if body.account_type not in ("free", "vip"):
        raise HTTPException(400, "account_type 必须是 'free' 或 'vip'")

    nickname = (body.nickname or "").strip()
    if not nickname:
        raise HTTPException(400, "nickname 不能为空")

    account.nickname = nickname
    account.account_type = body.account_type
    account.daily_limit = _daily_limit_for(body.account_type)
    if body.account_type == "vip":
        account.daily_used = 0
    else:
        account.daily_used = min(max(account.daily_used, 0), account.daily_limit)

    db.commit()
    db.refresh(account)
    return {"success": True, "account": _to_response(account)}


@router.post("/batch-type")
async def batch_update_type(body: BatchUpdateTypeRequest, db: Session = Depends(get_db)):
    if body.account_type not in ("free", "vip"):
        raise HTTPException(400, "account_type 必须是 'free' 或 'vip'")

    accounts = _get_accounts_by_ids(body.account_ids, db)
    updated_ids = []

    for account in accounts:
        if account.account_type != body.account_type:
            account.account_type = body.account_type
            account.daily_limit = _daily_limit_for(body.account_type)
            if body.account_type == "vip":
                account.daily_used = 0
            else:
                account.daily_used = min(max(account.daily_used, 0), account.daily_limit)
        updated_ids.append(account.id)

    db.commit()
    return {
        "success": True,
        "updated_count": len(updated_ids),
        "account_type": body.account_type,
        "account_ids": updated_ids,
    }


@router.put("/{account_id}/cookie")
async def refresh_cookie(account_id: int, body: UpdateCookieRequest, db: Session = Depends(get_db)):
    mgr = SessionManager(db)
    try:
        account = mgr.refresh_cookie(account_id, body.cookie)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if not account:
        raise HTTPException(404, f"账号 {account_id} 不存在")
    return {"success": True, "account": _to_response(account)}


@router.delete("/{account_id}")
async def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    db.delete(account)
    db.commit()
    return {"success": True}


@router.post("/{account_id}/check")
async def check_session(account_id: int, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)

    mgr = SessionManager(db)
    valid = await mgr.check_session(account)
    _apply_login_probe_state(account, valid)

    today_db_count = _count_today_originals(account_id, db)
    synced = False
    if today_db_count > account.daily_used:
        old_used = account.daily_used
        account.daily_used = today_db_count
        synced = True
        logger.info("[Accounts] 账号 %s daily_used 已向上同步: %s -> %s", account_id, old_used, today_db_count)

    db.commit()
    return {
        "account_id": account_id,
        "valid": valid,
        "daily_used": account.daily_used,
        "today_db_count": today_db_count,
        "synced": synced,
    }


@router.post("/check-all")
async def check_all_sessions(db: Session = Depends(get_db)):
    mgr = SessionManager(db)
    results = await mgr.check_all_sessions()
    accounts = db.query(Account).filter(Account.id.in_(results.keys())).all() if results else []

    for account in accounts:
        _apply_login_probe_state(account, bool(results.get(account.id)))

    if accounts:
        db.commit()
    return {"results": results}


@router.get("/pool")
async def get_pool_status(db: Session = Depends(get_db)):
    _normalize_daily_limits(db)
    pool = AccountPool(db=db)
    return pool.get_pool_status()


@router.post("/{account_id}/verify-quota")
async def verify_quota(account_id: int, db: Session = Depends(get_db)):
    """
    通过真实站点接口验证：
    1. cookie 是否仍然有效
    2. 当前账号是否可以获取原图
    """
    account = _get_account_or_404(account_id, db)
    result = await _verify_account_access(account)
    db.commit()
    return result


@router.post("/verify-batch")
async def verify_quota_batch(body: BatchVerifyRequest, db: Session = Depends(get_db)):
    accounts = _get_accounts_by_ids(body.account_ids, db)
    results = []

    for account in accounts:
        results.append(await _verify_account_access(account))

    db.commit()

    auth_invalid = sum(1 for item in results if item["auth_valid"] is False)
    original_ok = sum(1 for item in results if item["can_download_original"] is True)
    original_denied = sum(1 for item in results if item["can_download_original"] is False)
    unknown = len(results) - auth_invalid - original_ok - original_denied

    return {
        "success": True,
        "total": len(results),
        "summary": {
            "auth_invalid": auth_invalid,
            "original_ok": original_ok,
            "original_denied": original_denied,
            "unknown": unknown,
        },
        "results": results,
    }


@router.put("/{account_id}/daily_used")
async def update_daily_used(account_id: int, body: UpdateQuotaRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    if body.daily_used < 0:
        raise HTTPException(400, "daily_used 不能为负数")
    if account.account_type != "free":
        raise HTTPException(400, "仅免费账号支持手动校正配额")

    account.daily_used = min(body.daily_used, account.daily_limit)
    db.commit()
    db.refresh(account)
    logger.info("[Accounts] 账号 %s 手动校正配额: daily_used=%s", account_id, body.daily_used)
    return {"success": True, "account": _to_response(account)}
