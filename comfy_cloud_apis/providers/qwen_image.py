"""阿里云百炼 千问 Qwen-Image 图像生成 —— 直连官方 API。

契约（**同步接口**）：

    POST {base}/api/v1/services/aigc/multimodal-generation/generation
      -> {"output": {"choices": [{"finish_reason": "stop",
                                  "message": {"role": "assistant",
                                              "content": [{"image": "https://...png"}]}}]},
          "usage": {"image_count": 1, "width": 2048, "height": 2048},
          "request_id": "..."}

base = https://dashscope.aliyuncs.com（华北2 北京）
     / https://dashscope-intl.aliyuncs.com（新加坡）
     / https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com（业务空间专属，推荐）

这是本项目里**唯一明确支持反向提示词**的生图接口（negative_prompt）。

注意：
- ``size`` 格式是 ``宽*高``（不是 16:9）
- 只有 ``qwen-image`` / ``qwen-image-plus`` 支持**异步**接口，本节点走同步
- 图片 URL **仅 24 小时有效**，本项目会立即下载到本地
- 跨地域报错：Key、模型、域名必须属于同一地域
"""

from __future__ import annotations

from ..core.base import CloudImageNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri

PROVIDER = "Qwen/Wan"

BASE_URL_CN = "https://dashscope.aliyuncs.com"
BASE_URL_INTL = "https://dashscope-intl.aliyuncs.com"

MODELS = [
    "qwen-image-3.0-pro",
    "qwen-image-3.0",
    "qwen-image-2.0-pro",
    "qwen-image-2.0",
    "qwen-image-max",
    "qwen-image-plus",
    "qwen-image",
]
SIZES = [
    "2048*2048",
    "2688*1536",
    "1536*2688",
    "2368*1728",
    "1728*2368",
    "1664*928",
    "1472*1104",
    "1328*1328",
    "1104*1472",
    "928*1664",
]


class QwenImageProvider:
    KEY_ENV = ("DASHSCOPE_API_KEY",)
    FILE_KEY = "qwen"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "百炼根地址。北京 https://dashscope.aliyuncs.com，新加坡 https://dashscope-intl.aliyuncs.com；"
        "推荐使用业务空间专属域名 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com。"
        "Key、模型、域名必须属于同一地域。"
    )

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        model = kw.get("model", "qwen-image-2.0-pro")
        n = int(kw.get("n", 1) or 1)
        if model in ("qwen-image-max", "qwen-image-plus", "qwen-image"):
            if n != 1:
                raise ValueError(f"{model} 的 n 固定为 1。")
        elif not 1 <= n <= 6:
            raise ValueError("n 必须在 1–6 之间（qwen-image-2.0 系列）。")

        parameters = {
            "size": kw.get("size", "2048*2048"),
            "n": n,
            "prompt_extend": bool(kw.get("prompt_extend", True)),
            "watermark": bool(kw.get("watermark", False)),
        }
        neg = (kw.get("negative_prompt") or "").strip()
        if neg:
            parameters["negative_prompt"] = neg[:500]
        seed = kw.get("seed")
        if seed is not None and int(seed) >= 0:
            parameters["seed"] = int(seed)

        # 参考图（图像编辑）：官方用 content 里的 image 字段
        content = [{"text": prompt}]
        ref_url = (kw.get("reference_image_url") or "").strip()
        ref_tensor = kw.get("reference_image")
        if ref_url or ref_tensor is not None:
            content.append({"image": ref_url or tensor_to_data_uri(ref_tensor)})

        return {
            "model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        resp = await request_json(
            session,
            PROVIDER,
            "POST",
            f"{base}/api/v1/services/aigc/multimodal-generation/generation",
            headers,
            payload,
        )
        code = dig(resp, "code", default="")
        if code:
            raise RuntimeError(f"[{PROVIDER}] 错误 {code}：{dig(resp, 'message', default='')}")
        return resp

    @classmethod
    def task_id_of(cls, resp: dict) -> str:
        return ""  # 同步接口

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return "succeeded"

    @classmethod
    def results_of(cls, resp: dict) -> list:
        out = []
        for choice in dig(resp, "output", "choices", default=[]) or []:
            if not isinstance(choice, dict):
                continue
            for item in dig(choice, "message", "content", default=[]) or []:
                if isinstance(item, dict) and item.get("image"):
                    out.append({"url": item["image"]})
        return out

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "usage", default={}) or {}


class QwenImageNode(CloudImageNodeBase):
    IMPL = QwenImageProvider
    PROVIDER = PROVIDER
    KEY_ENV = QwenImageProvider.KEY_ENV
    FILE_KEY = QwenImageProvider.FILE_KEY
    DEFAULT_BASE_URL = QwenImageProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = QwenImageProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/Qwen"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "qwen-image-2.0-pro"}),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面描述。"},
                ),
                "size": (SIZES, {"default": "2048*2048"}),
            },
            "optional": {
                "negative_prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "反向提示词，最多 500 字符。"},
                ),
                "n": ("INT", {"default": 1, "min": 1, "max": 6, "tooltip": "生成张数。"}),
                "reference_image": ("IMAGE", {"tooltip": "参考图（图像编辑）。"}),
                "reference_image_url": ("STRING", {"default": "", "tooltip": "参考图 URL。"}),
                "prompt_extend": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "提示词智能改写。追求细节可控时建议关闭。"},
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
