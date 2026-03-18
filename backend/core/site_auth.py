"""
site_auth.py - 站点登录态与原图权限探测
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Optional

import httpx

from backend.core.anti_detection import AntiDetection
from backend.core.captcha_solver import AltchaSolver

BASE_URL = "https://haowallpaper.com"
AUTH_PROBE_URL = f"{BASE_URL}/link/pc/notify/getNtfyCount"
COMPLETE_URL = f"{BASE_URL}/link/common/file/getCompleteUrl"
ORIGINAL_ACCESS_TEST_WALLPAPER_ID = "18193748552895872"


def extract_token(cookie: str) -> str:
    """从 cookie 中提取 userData.token。"""
    match = re.search(r"userData=([^;,]+)", cookie or "")
    if not match:
        return ""

    try:
        encoded = urllib.parse.unquote(match.group(1).strip())
        return json.loads(encoded).get("token", "")
    except Exception:
        return ""


def build_auth_headers(
    cookie: str,
    referer: str = "https://haowallpaper.com/",
    extra: Optional[dict] = None,
    session_profile: Optional[dict] = None,
) -> dict:
    """构建与官网前端一致的登录态请求头。"""
    anti = AntiDetection(use_proxy=False)
    headers = anti.build_headers(cookie, referer=referer, profile=session_profile)
    headers["Cache-Control"] = "no-cache"
    token = extract_token(cookie)
    if token:
        headers["token"] = token
    if extra:
        headers.update(extra)
    return headers


def _parse_wrapper_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return f"HTTP {resp.status_code}"

    if isinstance(data, dict):
        return str(data.get("msg") or data.get("message") or f"HTTP {resp.status_code}")
    return f"HTTP {resp.status_code}"


async def probe_login_status(
    client: httpx.AsyncClient,
    cookie: str,
    session_profile: Optional[dict] = None,
) -> tuple[Optional[bool], str]:
    """
    探测账号登录态。

    Returns:
        (True, msg): 站点确认已登录
        (False, msg): 站点确认未授权 / cookie 失效
        (None, msg): 网络异常或限流，状态未知
    """
    headers = build_auth_headers(cookie, session_profile=session_profile)

    try:
        resp = await client.get(AUTH_PROBE_URL, headers=headers, timeout=10)
    except httpx.TimeoutException:
        return None, "登录态探测超时"
    except Exception as exc:
        return None, f"登录态探测异常: {exc}"

    if resp.status_code == 305:
        return None, "登录态探测被限流(305)"
    if resp.status_code in (401, 403):
        return False, _parse_wrapper_message(resp)

    try:
        data = resp.json()
    except Exception:
        return (True, "登录态探测通过") if resp.status_code == 200 else (None, f"HTTP {resp.status_code}")

    status = data.get("status")
    if resp.status_code == 200 and status == 200:
        return True, str(data.get("msg") or "登录态探测通过")
    if status in (401, 403):
        return False, str(data.get("msg") or "未授权")
    return None, str(data.get("msg") or f"HTTP {resp.status_code}")


async def probe_original_access(
    client: httpx.AsyncClient,
    cookie: str,
    captcha_solver: AltchaSolver,
    wallpaper_id: str = ORIGINAL_ACCESS_TEST_WALLPAPER_ID,
    session_profile: Optional[dict] = None,
) -> tuple[Optional[bool], int | None, str]:
    """
    探测账号是否能获取原图直链。

    Returns:
        (True, 200, msg): 可获取原图
        (False, 401, msg): 登录有效但无法获取原图
        (None, code, msg): 网络异常或状态未知
    """
    extra_headers = build_auth_headers(cookie, session_profile=session_profile)
    verified = await captcha_solver.verify_download(
        client,
        cookie,
        extra_headers=extra_headers,
        ua=session_profile.get("ua") if session_profile else None,
    )
    if not verified:
        return None, None, "altcha 验证失败"

    headers = build_auth_headers(cookie, session_profile=session_profile)
    try:
        resp = await client.get(
            f"{COMPLETE_URL}/{wallpaper_id}",
            headers=headers,
            timeout=10,
        )
    except httpx.TimeoutException:
        return None, None, "getCompleteUrl 超时"
    except Exception as exc:
        return None, None, f"getCompleteUrl 异常: {exc}"

    try:
        data = resp.json()
    except Exception:
        if resp.status_code == 200:
            return True, 200, "原图直链探测通过"
        return None, resp.status_code, f"getCompleteUrl 返回 HTTP {resp.status_code}"

    status = int(data.get("status") or resp.status_code)
    msg = str(data.get("msg") or "")
    if status == 200 and data.get("data"):
        return True, status, msg or "可正常获取原图"
    if status == 401:
        return False, status, msg or "站点未授予原图权限"
    if status == 305:
        return None, status, msg or "原图探测被限流"
    return None, status, msg or f"未知状态 {status}"
