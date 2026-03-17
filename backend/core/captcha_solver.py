"""
captcha_solver.py — altcha Proof-of-Work 求解器

工作原理：
  1. GET challengeurl 拿到 {challenge, maxnumber, algorithm, salt}
  2. 本地暴力枚举 nonce，计算 SHA-256(salt + nonce)
     直到 hash 与 challenge 匹配
  3. 将 base64(JSON({algorithm, challenge, number, salt, signature}))
     作为 altcha 表单字段值随下载请求提交
"""

import hashlib
import hmac
import json
import base64
import time
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 默认 challenge 接口地址
DEFAULT_CHALLENGE_URL = "https://haowallpaper.com/link/pc/certify/challenge"
# PoW 验证提交接口（POST ?payload=<base64_solution>）
VERIFY_URL = "https://haowallpaper.com/link/pc/certify/verify"


class AltchaSolver:
    """altcha PoW 验证码求解器"""

    def __init__(
        self,
        challenge_url: str = DEFAULT_CHALLENGE_URL,
        timeout: int = 10,
        max_retries: int = 3,
    ):
        self.challenge_url = challenge_url
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------ #
    #  公开方法
    # ------------------------------------------------------------------ #

    async def solve(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        extra_headers: Optional[dict] = None,
        ua: Optional[str] = None,
    ) -> Optional[str]:
        """
        完整求解流程：获取 challenge → 计算 PoW → 返回 altcha 字段值

        Args:
            client:        复用的 httpx.AsyncClient（带 cookie 和代理配置）
            cookie:        当前账号的 cookie 字符串
            extra_headers: 额外请求头
            ua:            User-Agent 字符串（传入任务级 session profile UA 保持一致性）

        Returns:
            base64 编码的 solution 字符串，提交时作为 "altcha" 字段值
            失败时返回 None
        """
        headers = self._build_headers(cookie, extra_headers, ua=ua)

        for attempt in range(1, self.max_retries + 1):
            try:
                # Step 1: 获取 challenge
                challenge_data = await self._fetch_challenge(client, headers)
                if not challenge_data:
                    logger.warning(f"[Altcha] 第 {attempt} 次获取 challenge 失败")
                    continue

                # Step 2: 本地计算 PoW
                t0 = time.perf_counter()
                solution = self._compute_pow(challenge_data)
                elapsed = time.perf_counter() - t0

                if solution is None:
                    logger.warning(f"[Altcha] 第 {attempt} 次 PoW 求解失败")
                    continue

                logger.info(f"[Altcha] PoW 求解成功，耗时 {elapsed:.3f}s，nonce={solution['number']}")
                return self._encode_solution(solution)

            except Exception as e:
                logger.error(f"[Altcha] 第 {attempt} 次异常: {e}")

        logger.error("[Altcha] 所有重试均失败")
        return None

    async def verify_download(
        self,
        client: httpx.AsyncClient,
        cookie: str,
        ua: Optional[str] = None,
    ) -> bool:
        """
        完整验证流程：获取 challenge → 计算 PoW → POST /certify/verify

        验证成功后，同一 client 会话即可调用 getCompleteUrl 获取原图直链。
        必须与后续 getCompleteUrl 请求使用同一个 httpx.AsyncClient 实例。

        Args:
            ua: User-Agent 字符串（传入任务级 session profile UA 保持一致性）

        Returns:
            True 表示验证成功，False 表示失败
        """
        solution = await self.solve(client, cookie, ua=ua)
        if not solution:
            logger.error("[Altcha] verify_download: PoW 求解失败")
            return False

        headers = self._build_headers(cookie, ua=ua)
        try:
            resp = await client.post(
                VERIFY_URL,
                params={"payload": solution},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == 200 and data.get("data") == "ok":
                logger.info("[Altcha] 人机验证成功")
                return True
            logger.warning("[Altcha] 验证接口返回非成功: %s", data)
            return False
        except Exception as e:
            logger.error("[Altcha] verify_download 异常: %s", e)
            return False

    # ------------------------------------------------------------------ #
    #  内部方法
    # ------------------------------------------------------------------ #

    async def _fetch_challenge(
        self, client: httpx.AsyncClient, headers: dict
    ) -> Optional[dict]:
        """GET challengeurl 获取 challenge 参数"""
        try:
            resp = await client.get(
                self.challenge_url,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.debug(f"[Altcha] challenge 响应: {data}")

            # 兼容两种响应格式
            # 格式1: {"challenge": "...", "maxnumber": 1000000, "salt": "...", "algorithm": "SHA-256"}
            # 格式2: {"data": {"challenge": ..., ...}}
            if "data" in data:
                data = data["data"]

            required = {"challenge", "salt", "algorithm"}
            if not required.issubset(data.keys()):
                logger.error(f"[Altcha] challenge 响应缺少必要字段: {data}")
                return None

            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"[Altcha] challenge 请求失败: HTTP {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"[Altcha] challenge 请求异常: {e}")
            return None

    def _compute_pow(self, challenge_data: dict) -> Optional[dict]:
        """
        暴力枚举 nonce 求解 PoW

        altcha 算法：
          hash = SHA-256(salt + str(nonce))
          当 hash == challenge 时求解成功

        部分实现中 challenge = HMAC-SHA256(salt+nonce, secret)，
        此时需要服务端 secret，本实现按标准 altcha 开源库处理。
        """
        algorithm: str = challenge_data.get("algorithm", "SHA-256").upper()
        challenge: str = challenge_data["challenge"]
        salt: str = challenge_data["salt"]
        max_number: int = int(challenge_data.get("maxnumber", 1_000_000))

        if algorithm not in ("SHA-256", "SHA-384", "SHA-512"):
            logger.error(f"[Altcha] 不支持的算法: {algorithm}")
            return None

        hash_fn = {
            "SHA-256": hashlib.sha256,
            "SHA-384": hashlib.sha384,
            "SHA-512": hashlib.sha512,
        }[algorithm]

        logger.debug(f"[Altcha] 开始枚举 nonce，范围 0~{max_number}")

        for nonce in range(max_number + 1):
            payload = f"{salt}{nonce}".encode("utf-8")
            digest = hash_fn(payload).hexdigest()
            if digest == challenge:
                return {
                    "algorithm": challenge_data.get("algorithm", "SHA-256"),
                    "challenge": challenge,
                    "number": nonce,
                    "salt": salt,
                    "signature": challenge_data.get("signature", ""),
                }

        logger.warning(f"[Altcha] 在范围 0~{max_number} 内未找到 nonce")
        return None

    @staticmethod
    def _encode_solution(solution: dict) -> str:
        """
        将 solution 字典序列化为 base64 字符串
        （altcha widget 期望的格式）
        """
        payload = json.dumps(solution, separators=(",", ":"), ensure_ascii=False)
        return base64.b64encode(payload.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _build_headers(
        cookie: str,
        extra: Optional[dict] = None,
        ua: Optional[str] = None,
    ) -> dict:
        """
        构建 altcha 请求头。

        Args:
            ua: 外部传入的 User-Agent（任务级 session profile），
                None 时使用内置默认 UA（Chrome 133）。
        """
        _ua = ua or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        )
        headers = {
            "Cookie": cookie,
            "User-Agent": _ua,
            "Referer": "https://haowallpaper.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if extra:
            headers.update(extra)
        return headers


# ------------------------------------------------------------------ #
#  独立测试入口
# ------------------------------------------------------------------ #

async def _test():
    """独立运行测试：python -m backend.core.captcha_solver"""
    import asyncio

    solver = AltchaSolver()
    async with httpx.AsyncClient() as client:
        # 测试时填入真实 cookie
        result = await solver.solve(client, cookie="test_cookie=1")
        print(f"Solution: {result}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_test())
