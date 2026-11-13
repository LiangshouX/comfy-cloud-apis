"""HTTP 层：统一的异步请求、错误翻译与下载。

设计要点：
- 错误不是"抛一个 HTTPError"，而是翻译成**用户能立刻采取行动**的句子。
- 下载成片时**默认不携带 Authorization 头**（成片 URL 通常指向 CDN/OSS，
  把 Key 发给存储域名是多余的暴露面）。
"""

from __future__ import annotations

import json as _json
from typing import Any, Optional

import aiohttp


class CloudError(RuntimeError):
    """云端 API 错误，带上可执行的处理建议。"""

    def __init__(self, provider: str, status: int, message: str, hint: str = ""):
        self.provider = provider
        self.status = status
        self.message = message
        self.hint = hint
        text = f"[{provider}] HTTP {status}：{message}"
        if hint:
            text += f"\n  → {hint}"
        super().__init__(text)


# 各家的通用 HTTP 语义提示；provider 可覆盖
_GENERIC_HINTS = {
    400: "请求参数被拒。检查模型名、必填参数与取值范围。",
    401: "鉴权失败。检查 API Key 是否正确、是否过期、是否与 base_url 属于同一地域。",
    402: "账户余额不足或额度耗尽，请到平台控制台充值。",
    403: "账号无权调用该模型，或该模型未开通。",
    404: "路径或模型不存在。检查 base_url 与模型 ID。",
    413: "请求体过大。图片请改用公网 URL，而不是内联 base64。",
    422: "内容被安全策略拦截，请改写提示词或素材。",
    429: "触发限流。视频生成多为异步任务，请串行排队，不要同时提交多个节点。",
    500: "服务端错误，稍后重试。",
    502: "网关错误，稍后重试。",
    503: "服务暂时不可用，稍后重试。",
    504: "网关超时，稍后重试。",
}

_PROVIDER_HINTS: dict[str, dict[int, str]] = {
    "MiniMax": {
        404: "多数情况是 base_url 带了 /v1。本项目使用 V2 路径（/v2/...），"
             "国内填 https://api.minimax.chat，国际填 https://api.minimaxi.chat。",
        429: "MiniMax 官方文档：免费额度下 H3 V2 最多 2 个并发任务，付费额度 15 个。",
    },
    "Seedance": {
        404: "检查 base_url 是否为 https://ark.cn-beijing.volces.com/api/v3，"
             "以及 model 是否是已开通的模型 ID（需要在方舟控制台创建推理接入点）。",
        429: "火山方舟按账号维度限流，建议串行提交。",
    },
    "Qwen/Wan": {
        404: "检查 base_url 与地域是否匹配：北京 dashscope.aliyuncs.com，"
             "新加坡 dashscope-intl.aliyuncs.com；使用业务空间专属域名时 URL 形如 "
             "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com。",
        400: "DashScope 常见原因：模型与地域不匹配，或缺少 X-DashScope-Async: enable 头。",
    },
}


def _hint_for(provider: str, status: int) -> str:
    return _PROVIDER_HINTS.get(provider, {}).get(status) or _GENERIC_HINTS.get(status, "")


async def request_json(
    session: aiohttp.ClientSession,
    provider: str,
    method: str,
    url: str,
    headers: dict,
    payload: Optional[dict] = None,
    timeout: float = 120.0,
) -> dict:
    """发一个 JSON 请求，返回解析后的 dict。"""
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.request(method, url, headers=headers, json=payload, timeout=req_timeout) as resp:
        text = await resp.text()
        if resp.status >= 400:
            raise CloudError(provider, resp.status, text[:1500], _hint_for(provider, resp.status))
        try:
            data = _json.loads(text)
        except Exception:
            raise CloudError(provider, resp.status, f"响应不是合法 JSON：{text[:600]}")
        return data if isinstance(data, dict) else {"_raw": data}


async def download_to(
    session: aiohttp.ClientSession,
    url: str,
    dest_path: str,
    timeout: float = 600.0,
    extra_headers: Optional[dict] = None,
) -> str:
    """把远程文件流式下载到本地。

    默认**不附带任何鉴权头**：绝大多数成片 URL 是带签名的公开链接，
    多带一个 Authorization 头反而让 Key 落到存储服务日志里。
    """
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.get(url, headers=extra_headers or {}, timeout=req_timeout) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"下载成片失败 HTTP {resp.status}：{url[:200]}")
        with open(dest_path, "wb") as fh:
            while True:
                chunk = await resp.content.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
    return dest_path


async def download_bytes(
    session: aiohttp.ClientSession,
    url: str,
    timeout: float = 300.0,
    extra_headers: Optional[dict] = None,
) -> bytes:
    """把远程文件下载成字节。

    图片体积小，直接进内存比落盘再读更简单，也方便**嗅探真实格式**
    （各家返回的 URL 后缀与实际 MIME 经常对不上）。

    同样**不附带任何鉴权头**。
    """
    req_timeout = aiohttp.ClientTimeout(total=timeout)
    async with session.get(url, headers=extra_headers or {}, timeout=req_timeout) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"下载图片失败 HTTP {resp.status}：{url[:200]}")
        return await resp.read()


def dig(data: Any, *paths, default=None):
    """容错取值：paths 依次尝试，返回第一个非 None 的值。

    用来兼容同一家厂商不同版本返回结构的差异（例如 Seedance 的
    content.video_url 既有对象也有裸字符串两种形态）。
    """
    cur = data
    for path in paths:
        if isinstance(path, str):
            if not isinstance(cur, dict):
                return default
            cur = cur.get(path)
        elif isinstance(path, int):
            if not isinstance(cur, (list, tuple)) or len(cur) <= path:
                return default
            cur = cur[path]
        else:
            return default
        if cur is None:
            return default
    return cur
