"""通义万相 文生图 —— 直连阿里云百炼官方 API（**异步**）。

契约：

    POST {base}/api/v1/services/aigc/text2image/image-synthesis
         必需请求头 X-DashScope-Async: enable
      -> {"output": {"task_id": "...", "task_status": "PENDING"}}

    GET {base}/api/v1/tasks/{task_id}
      -> {"output": {"task_status": "SUCCEEDED",
                     "results": [{"url": "https://...png"}]},
          "usage": {"image_count": 1}}

base = https://dashscope.aliyuncs.com（华北2 北京）
     / https://dashscope-intl.aliyuncs.com（新加坡）
     / https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com（业务空间专属，推荐）

⚠️ 缺 ``X-DashScope-Async: enable`` 会直接报
   "current user api does not support synchronous calls"。

这个节点覆盖了本项目的**异步生图**路径（另外三家都是同步接口），
所以它带完整的轮询参数与「任务查询」节点。
"""

from __future__ import annotations

from ..core.base import CloudImageNodeBase, CloudTaskQueryNode
from ..core.http import dig, request_json
from ..core.task import normalize_status

PROVIDER = "Qwen/Wan"

BASE_URL_CN = "https://dashscope.aliyuncs.com"
BASE_URL_INTL = "https://dashscope-intl.aliyuncs.com"

MODELS = [
    "wan2.6-t2i",
    "wan2.5-t2i-preview",
    "wan2.2-t2i-plus",
    "wan2.2-t2i-flash",
    "wan2.1-t2i-plus",
    "wan2.1-t2i-turbo",
    "z-image-turbo",
]
SIZES = [
    "1024*1024",
    "1280*720",
    "720*1280",
    "1440*1440",
    "960*540",
    "540*960",
    "1440*810",
    "810*1440",
]


class WanImageProvider:
    KEY_ENV = ("DASHSCOPE_API_KEY",)
    FILE_KEY = "qwen"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "百炼根地址。北京 https://dashscope.aliyuncs.com，新加坡 https://dashscope-intl.aliyuncs.com；"
        "推荐使用业务空间专属域名 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com。"
        "Key、模型、域名必须属于同一地域。"
    )

    @classmethod
    def extra_headers(cls) -> dict:
        # 缺这个头会报 "current user api does not support synchronous calls"
        return {"X-DashScope-Async": "enable"}

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        n = int(kw.get("n", 1) or 1)
        if not 1 <= n <= 4:
            raise ValueError("n 必须在 1–4 之间。")

        parameters = {
            "size": kw.get("size", "1024*1024"),
            "n": n,
            "prompt_extend": bool(kw.get("prompt_extend", True)),
            "watermark": bool(kw.get("watermark", False)),
        }
        seed = kw.get("seed")
        if seed is not None and int(seed) >= 0:
            parameters["seed"] = int(seed)

        return {
            "model": kw.get("model", "wan2.6-t2i"),
            "input": {"prompt": prompt},
            "parameters": parameters,
        }

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        resp = await request_json(
            session,
            PROVIDER,
            "POST",
            f"{base}/api/v1/services/aigc/text2image/image-synthesis",
            headers,
            payload,
        )
        code = dig(resp, "code", default="")
        if code:
            raise RuntimeError(f"[{PROVIDER}] 错误 {code}：{dig(resp, 'message', default='')}")
        return resp

    @classmethod
    def task_id_of(cls, resp: dict) -> str:
        return str(dig(resp, "output", "task_id", default="") or "")

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await request_json(session, PROVIDER, "GET", f"{base}/api/v1/tasks/{task_id}", headers)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return normalize_status(dig(resp, "output", "task_status"))

    @classmethod
    def results_of(cls, resp: dict) -> list:
        out = []
        for item in dig(resp, "output", "results", default=[]) or []:
            if isinstance(item, dict) and item.get("url"):
                out.append({"url": item["url"]})
        return out

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "usage", default={}) or {}


class WanImageNode(CloudImageNodeBase):
    IMPL = WanImageProvider
    ASYNC = True
    PROVIDER = PROVIDER
    KEY_ENV = WanImageProvider.KEY_ENV
    FILE_KEY = WanImageProvider.FILE_KEY
    DEFAULT_BASE_URL = WanImageProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = WanImageProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/Qwen"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "wan2.6-t2i"}),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面描述。"},
                ),
                "size": (SIZES, {"default": "1024*1024"}),
            },
            "optional": {
                "n": ("INT", {"default": 1, "min": 1, "max": 4, "tooltip": "生成张数。"}),
                "prompt_extend": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "提示词智能改写。会额外增加 3–4 秒。"},
                ),
                "watermark": ("BOOLEAN", {"default": False}),
                "seed": (
                    "INT",
                    {"default": -1, "min": -1, "max": 2147483647,
                     "tooltip": "随机种子。-1 表示随机。"},
                ),
                **cls.common_optional(),
            },
        }


class WanImageTaskQueryNode(CloudTaskQueryNode):
    IMPL = WanImageProvider
    PROVIDER = PROVIDER
    KEY_ENV = WanImageProvider.KEY_ENV
    FILE_KEY = WanImageProvider.FILE_KEY
    DEFAULT_BASE_URL = WanImageProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = WanImageProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/Qwen"

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await WanImageProvider.fetch(session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return WanImageProvider.status_of(resp)
