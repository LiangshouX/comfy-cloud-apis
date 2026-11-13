"""MiniMax 图像生成 —— 直连官方 V1 API。

契约：

    POST {base}/v1/image_generation
      -> {"id": "...", "data": {"image_urls": [...] | "image_base64": [...]},
          "metadata": {"success_count": N, "failed_count": N},
          "base_resp": {"status_code": 0, "status_msg": "success"}}

这是**同步接口**：一次请求直接返回图片，没有 task_id、没有轮询。

⚠️ 业务错误藏在 HTTP 200 的响应体里：``base_resp.status_code`` 非 0 就是失败
（1008 余额不足、1026 内容涉敏、2013 参数异常），必须单独检查，
否则会拿到一个"成功但没有图片"的空响应。

⚠️ 注意路径是 /v1（与视频的 H3 V2 不同）。这里用 normalize_base_url 把
用户误粘的 /v1 去掉，再由 create() 补回，避免出现 /v1/v1。
"""

from __future__ import annotations

from ..core.base import CloudImageNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri

PROVIDER = "MiniMax"

BASE_URL_CN = "https://api.minimax.chat"
BASE_URL_INTL = "https://api.minimaxi.chat"
BASE_URL_ALT = "https://api.minimax.io"

MODELS = ["image-01", "image-01-live"]
ASPECT_RATIOS = ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]
STYLE_TYPES = ["漫画", "元气", "中世纪", "水彩"]


class MiniMaxImageProvider:
    KEY_ENV = ("MINIMAX_API_KEY", "MINIMAX_TOKEN")
    FILE_KEY = "minimax"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "MiniMax 开放平台根域名。国内用 https://api.minimax.chat，国际用 https://api.minimaxi.chat。"
        "本节点走 /v1/image_generation。"
    )

    @classmethod
    def normalize_base_url(cls, raw: str) -> str:
        base = (raw or "").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")
        if len(prompt) > 1500:
            raise ValueError("prompt 超过 MiniMax 的 1500 字符上限，请精简。")

        n = int(kw.get("n", 1) or 1)
        if not 1 <= n <= 9:
            raise ValueError("n 必须在 1–9 之间（官方上限 9）。")

        payload = {
            "model": kw.get("model", "image-01"),
            "prompt": prompt,
            "response_format": kw.get("response_format", "url"),
            "n": n,
            "seed": int(kw.get("seed", 0) or 0),
            "prompt_optimizer": bool(kw.get("prompt_optimizer", False)),
            "aigc_watermark": bool(kw.get("aigc_watermark", False)),
        }

        # 官方规则：aspect_ratio 与 width/height 同时给时 aspect_ratio 优先，
        # 所以自定义尺寸时**不下发** aspect_ratio。
        width = int(kw.get("width", 0) or 0)
        height = int(kw.get("height", 0) or 0)
        if width and height:
            for v in (width, height):
                if not 512 <= v <= 2048 or v % 8 != 0:
                    raise ValueError("width/height 必须在 512–2048 之间且是 8 的倍数。")
            payload["width"] = width
            payload["height"] = height
        else:
            payload["aspect_ratio"] = kw.get("aspect_ratio", "1:1")

        # 图生图：subject_reference 只支持单张参考图
        ref_tensor = kw.get("reference_image")
        ref_url = (kw.get("reference_image_url") or "").strip()
        if ref_tensor is not None or ref_url:
            payload["subject_reference"] = [
                {
                    "type": "character",
                    "image_file": ref_url or tensor_to_data_uri(ref_tensor),
                }
            ]

        # style 仅 image-01-live 支持
        style_type = (kw.get("style_type") or "").strip()
        if style_type:
            if payload["model"] != "image-01-live":
                raise ValueError("style 参数只有 image-01-live 支持。")
            payload["style"] = {
                "style_type": style_type,
                "style_weight": float(kw.get("style_weight", 0.8) or 0.8),
            }

        return payload

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        resp = await request_json(
            session, PROVIDER, "POST", f"{base}/v1/image_generation", headers, payload
        )
        # 业务错误在 200 的响应体里
        base_resp = dig(resp, "base_resp", default={}) or {}
        code = base_resp.get("status_code")
        if code not in (0, None):
            raise RuntimeError(
                f"[{PROVIDER}] 业务错误 status_code={code}：{base_resp.get('status_msg')}\n"
                f"  常见码：1008 余额不足 / 1026 内容涉敏 / 2013 参数异常"
            )
        return resp

    @classmethod
    def task_id_of(cls, resp: dict) -> str:
        return ""  # 同步接口

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return "succeeded"

    @classmethod
    def results_of(cls, resp: dict) -> list:
        urls = dig(resp, "data", "image_urls", default=None)
        if urls:
            return [{"url": u} for u in urls]
        b64 = dig(resp, "data", "image_base64", default=None)
        if b64:
            return [{"base64": b} for b in b64]
        return []

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        meta = dig(resp, "metadata", default={}) or {}
        return {
            "success_count": meta.get("success_count"),
            "failed_count": meta.get("failed_count"),
            "id": dig(resp, "id", default=""),
        }


class MiniMaxImageNode(CloudImageNodeBase):
    IMPL = MiniMaxImageProvider
    PROVIDER = PROVIDER
    KEY_ENV = MiniMaxImageProvider.KEY_ENV
    FILE_KEY = MiniMaxImageProvider.FILE_KEY
    DEFAULT_BASE_URL = MiniMaxImageProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = MiniMaxImageProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/MiniMax"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "image-01"}),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面描述，最多 1500 字符。"},
                ),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "1:1"}),
                "n": ("INT", {"default": 1, "min": 1, "max": 9, "step": 1}),
                "seed": (
                    "INT",
                    {"default": 42, "min": 0, "max": 4294967295, "control_after_generate": True},
                ),
            },
            "optional": {
                "reference_image": ("IMAGE", {"tooltip": "图生图参考图（人物参考）。官方每次只支持 1 张。"}),
                "reference_image_url": (
                    "STRING",
                    {"default": "", "tooltip": "参考图 URL（填了则忽略 reference_image）。"},
                ),
                "response_format": (
                    ["url", "base64"],
                    {
                        "default": "url",
                        "tooltip": "url 有效期 24 小时（项目会立即下载到本地）；base64 直接内联返回。",
                    },
                ),
                "prompt_optimizer": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "开启后由 MiniMax 自动优化提示词。"},
                ),
                "aigc_watermark": ("BOOLEAN", {"default": False}),
                "width": (
                    "INT",
                    {"default": 0, "min": 0, "max": 2048, "step": 8,
                     "tooltip": "自定义宽度（0 = 用 aspect_ratio）。仅 image-01 生效，512–2048 且为 8 的倍数。"},
                ),
                "height": (
                    "INT",
                    {"default": 0, "min": 0, "max": 2048, "step": 8,
                     "tooltip": "自定义高度（0 = 用 aspect_ratio）。"},
                ),
                "style_type": (
                    STYLE_TYPES + [""],
                    {"default": "", "tooltip": "风格预设，仅 image-01-live 支持。"},
                ),
                "style_weight": ("FLOAT", {"default": 0.8, "min": 0.01, "max": 1.0, "step": 0.05}),
                **cls.common_optional(),
            },
        }
