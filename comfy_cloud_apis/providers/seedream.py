"""火山方舟 Seedream（即梦同源）图像生成 —— 直连官方 v3 API。

契约：

    POST {base}/images/generations
      -> {"model": "...", "created": 1757321139,
          "data": [{"url": "..." | "b64_json": "...", "size": "2048x2048"}],
          "usage": {"generated_images": 1, "output_tokens": 16280}}

base = https://ark.cn-beijing.volces.com/api/v3
这是**同步接口**：一次请求直接返回图片。

能力要点：
- 图生图/多图融合：``image`` 字段接受 URL 字符串或 URL 数组，
  也明确支持 base64（``data:image/png;base64,...``）
- 组图：``sequential_image_generation="auto"`` +
  ``sequential_image_generation_options.max_images``
- 分辨率：``size`` 可写 "2K"/"4K" 或具体 "2048x2048"
- 联网搜索：仅 5.0 系列，``tools: [{"type": "web_search"}]``
- 图片 URL **仅 24 小时有效**，本项目会立即下载到本地
"""

from __future__ import annotations

from ..core.base import CloudImageNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri

PROVIDER = "Seedance"

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

MODELS = [
    "doubao-seedream-5-0-lite-260128",
    "doubao-seedream-5-0-260128",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-4-0-250828",
    "doubao-seedream-3-0-t2i-250415",
]
SIZES = ["1K", "2K", "3K", "4K", "1024x1024", "2048x2048", "2048x1152", "1152x2048"]


class SeedreamProvider:
    KEY_ENV = ("ARK_API_KEY",)
    FILE_KEY = "seedance"
    DEFAULT_BASE_URL = BASE_URL
    BASE_URL_HINT = (
        "火山方舟 v3 根地址：https://ark.cn-beijing.volces.com/api/v3。"
        "model 必须是控制台里创建过推理接入点的模型 ID。"
    )

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        model = kw.get("model", "doubao-seedream-4-0-250828")
        payload = {
            "model": model,
            "prompt": prompt,
            "size": kw.get("size", "2K"),
            "response_format": kw.get("response_format", "url"),
            "watermark": bool(kw.get("watermark", False)),
        }

        # 组图：仅 4.0 / 4.5 / 5.0 支持
        max_images = int(kw.get("max_images", 1) or 1)
        if max_images > 1:
            if model not in {
                "doubao-seedream-5-0-lite-260128",
                "doubao-seedream-5-0-260128",
                "doubao-seedream-4-5-251128",
                "doubao-seedream-4-0-250828",
            }:
                raise ValueError("组图（max_images > 1）只有 Seedream 4.0 / 4.5 / 5.0 支持。")
            if not 1 <= max_images <= 15:
                raise ValueError("max_images 必须在 1–15 之间。")
            payload["sequential_image_generation"] = "auto"
            payload["sequential_image_generation_options"] = {"max_images": max_images}

        # 参考图：URL 数组或 base64；3.0-t2i 不支持
        refs = []
        ref_url = (kw.get("reference_image_url") or "").strip()
        if ref_url:
            refs.append(ref_url)
        for i in (1, 2, 3, 4):
            v = kw.get(f"reference_image_{i}")
            if v is not None:
                refs.append(tensor_to_data_uri(v))
        if refs:
            if model == "doubao-seedream-3-0-t2i-250415":
                raise ValueError("doubao-seedream-3-0-t2i 只支持文生图，不接受参考图。")
            payload["image"] = refs[0] if len(refs) == 1 else refs

        # 提示词优化：4.0 / 4.5 / 5.0 支持
        mode = (kw.get("optimize_prompt_mode") or "").strip()
        if mode:
            if model not in {
                "doubao-seedream-5-0-lite-260128",
                "doubao-seedream-4-5-251128",
                "doubao-seedream-4-0-250828",
            }:
                raise ValueError("optimize_prompt_mode 只有 Seedream 4.0 / 4.5 / 5.0-lite 支持。")
            payload["optimize_prompt_options"] = {"mode": mode}

        # output_format：仅 5.0 支持
        out_fmt = (kw.get("output_format") or "").strip()
        if out_fmt:
            if not model.startswith("doubao-seedream-5-0"):
                raise ValueError("output_format 只有 Seedream 5.0 系列支持。")
            payload["output_format"] = out_fmt

        # seed / guidance_scale：仅 3.0-t2i 支持
        seed = kw.get("seed")
        if seed is not None and int(seed) >= 0:
            if model != "doubao-seedream-3-0-t2i-250415":
                raise ValueError("seed 只有 doubao-seedream-3-0-t2i 支持。")
            payload["seed"] = int(seed)

        # 联网搜索：仅 5.0 支持
        if kw.get("web_search"):
            if not model.startswith("doubao-seedream-5-0"):
                raise ValueError("联网搜索（web_search）只有 Seedream 5.0 系列支持。")
            payload["tools"] = [{"type": "web_search"}]

        return payload

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        resp = await request_json(session, PROVIDER, "POST", f"{base}/images/generations", headers, payload)
        err = dig(resp, "error", default=None)
        if err:
            raise RuntimeError(f"[{PROVIDER}] 错误：{err}")
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
        for item in dig(resp, "data", default=[]) or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            b64 = item.get("b64_json")
            if url:
                out.append({"url": url})
            elif b64:
                out.append({"base64": b64})
        return out

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "usage", default={}) or {}


class SeedreamImageNode(CloudImageNodeBase):
    IMPL = SeedreamProvider
    PROVIDER = PROVIDER
    KEY_ENV = SeedreamProvider.KEY_ENV
    FILE_KEY = SeedreamProvider.FILE_KEY
    DEFAULT_BASE_URL = SeedreamProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = SeedreamProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "doubao-seedream-4-0-250828"}),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面描述，建议不超过 300 汉字。"},
                ),
                "size": (SIZES, {"default": "2K"}),
            },
            "optional": {
                "reference_image_1": ("IMAGE", {"tooltip": "参考图 1（图生图 / 多图融合）。"}),
                "reference_image_2": ("IMAGE", {"tooltip": "参考图 2。"}),
                "reference_image_3": ("IMAGE", {"tooltip": "参考图 3。"}),
                "reference_image_4": ("IMAGE", {"tooltip": "参考图 4。"}),
                "reference_image_url": (
                    "STRING",
                    {"default": "", "tooltip": "参考图 URL（公网可达）。与上面的 IMAGE 输入可混用。"},
                ),
                "max_images": (
                    "INT",
                    {"default": 1, "min": 1, "max": 15,
                     "tooltip": "组图张数。仅 4.0/4.5/5.0 支持，且「参考图数 + 生成数」需 ≤ 15。"},
                ),
                "response_format": (["url", "b64_json"], {"default": "url"}),
                "output_format": (["", "png", "jpeg"], {"default": "", "tooltip": "仅 Seedream 5.0 支持。"}),
                "optimize_prompt_mode": (
                    ["", "standard", "fast"],
                    {"default": "", "tooltip": "提示词优化模式。standard 更准但更慢。"},
                ),
                "watermark": ("BOOLEAN", {"default": False}),
                "web_search": ("BOOLEAN", {"default": False, "tooltip": "联网检索，仅 Seedream 5.0 支持。"}),
                "seed": (
                    "INT",
                    {"default": -1, "min": -1, "max": 2147483647,
                     "tooltip": "随机种子，仅 doubao-seedream-3-0-t2i 支持。-1 表示随机。"},
                ),
                **cls.common_optional(),
            },
        }
