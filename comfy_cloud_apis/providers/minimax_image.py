"""MiniMax 图像生成 —— 直连官方 API。

⚠️ **MiniMax 有两套完全不同的生图接口**，不要混用：

=== 旧接口（image-01 系列） ===

    POST {base}/v1/image_generation            ← 单数
      -> {"id": "...", "data": {"image_urls": [...]}, "metadata": {...},
          "base_resp": {"status_code": 0, ...}}

* 端点 ``/v1/image_generation``（单数）
* ``data`` 是**对象**，图片在 ``data.image_urls``
* 业务错误藏在 HTTP 200 的 ``base_resp.status_code`` 里
* 提示词 ≤ 1500 字符，n ∈ [1,9]

=== 新接口（H3-Image 系列） ===

    POST {base}/v1/images/generations           ← 复数（文生图）
    POST {base}/v1/images/edits                 ← 复数（图像编辑，1–16 张参考图）
      -> {"created": ..., "data": [{"url": "...", "size": "...", "revised_prompt": "..."},
                                   {"error": {"code": "1027", "message": "..."}}],
          "output_format": "jpeg",
          "usage": {"generated_images": 1, "total_tokens": 7254,
                    "input_tokens": 3174, "output_tokens": 4080,
                    "input_tokens_details": {"text_tokens": 3174, "image_tokens": 0},
                    "output_tokens_details": {"image_tokens": 4080}},
          "request_id": "..."}

* 端点 ``/v1/images/generations`` / ``/v1/images/edits``（复数）
* ``data`` 是**数组**，每张图一项；失败的项**只有 error**
* 提示词 ≤ 32000 字符，n ∈ [1,10]
* **该端点不幂等**：请求一旦发出，服务器就会跑完并计费，
  即使客户端超时或断开；重试会重复生成、重复计费。
  → 客户端超时必须给足（服务器最多等 600 秒）。

域名：

    国内   https://api.minimax.cn      （新，推荐）
    国际   https://api.minimax.io
    旧国内  https://api.minimax.chat   （仍可用）
    旧国际  https://api.minimaxi.chat
"""

from __future__ import annotations

from ..core.base import CloudImageNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri

PROVIDER = "MiniMax"

BASE_URL_CN = "https://api.minimax.cn"
BASE_URL_INTL = "https://api.minimax.io"
BASE_URL_CN_LEGACY = "https://api.minimax.chat"
BASE_URL_INTL_LEGACY = "https://api.minimaxi.chat"

# 旧接口模型
LEGACY_MODELS = ["image-01", "image-01-live"]
# 新接口模型
H3_IMAGE_MODELS = ["MiniMax-H3-Image", "MiniMax-H3-Image-Highspeed"]
MODELS = LEGACY_MODELS + H3_IMAGE_MODELS

# 两套接口共同支持的宽高比（交集）
ASPECT_RATIOS = ["auto", "1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]
# 仅 H3-Image 支持的清晰度档
AREAS = ["1K", "2K", "4K"]
STYLE_TYPES = ["漫画", "元气", "中世纪", "水彩"]

# H3-Image 的服务器最长等待 600 秒，客户端要留余量
H3_TIMEOUT = 660.0


def _is_h3_image(model: str) -> bool:
    return (model or "") in H3_IMAGE_MODELS


class MiniMaxImageProvider:
    KEY_ENV = ("MINIMAX_API_KEY", "MINIMAX_TOKEN")
    FILE_KEY = "minimax"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "MiniMax 开放平台根域名。国内 https://api.minimax.cn，国际 https://api.minimax.io；"
        "旧域名 api.minimax.chat / api.minimaxi.chat 仍可用。"
    )

    @classmethod
    def normalize_base_url(cls, raw: str) -> str:
        base = (raw or "").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base

    # ------------------------------------------------------------------ #
    # 请求体
    # ------------------------------------------------------------------ #
    @classmethod
    def build_payload(cls, **kw) -> dict:
        model = kw.get("model", "image-01")
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        h3 = _is_h3_image(model)

        # 提示词长度上限按模型不同
        limit = 32000 if h3 else 1500
        if len(prompt) > limit:
            raise ValueError(f"prompt 超过 {model} 的 {limit} 字符上限。")

        n = int(kw.get("n", 1) or 1)
        max_n = 10 if h3 else 9
        if not 1 <= n <= max_n:
            raise ValueError(f"n 必须在 1–{max_n} 之间（{model} 的官方上限）。")

        payload: dict = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "seed": int(kw.get("seed", 0) or 0),
        }

        # ---- 尺寸 ----
        # 旧接口：aspect_ratio（固定 8 个）或 width/height（512–2048，8 的倍数）
        # 新接口：size="WxH" 或 aspect_ratio + area（size 与 aspect_ratio/area 互斥）
        size = (kw.get("size") or "").strip().lower()
        aspect_ratio = (kw.get("aspect_ratio") or "auto").strip()
        area = (kw.get("area") or "4K").strip()

        if h3:
            # 节点下拉给的是 "base64"，新接口原生叫 "b64_json"
            payload["response_format"] = (
                "b64_json" if kw.get("response_format") == "base64" else (kw.get("response_format") or "url")
            )

            out_fmt = (kw.get("output_format") or "").strip().lower()
            if out_fmt:
                if out_fmt not in ("jpeg", "jpg", "png", "webp"):
                    raise ValueError("output_format 只能是 jpeg / png / webp。")
                payload["output_format"] = "jpeg" if out_fmt == "jpg" else out_fmt
            if payload.get("output_format") in ("jpeg", "webp"):
                payload["output_compression"] = int(kw.get("output_compression", 95) or 95)

            if size:
                # size 与 aspect_ratio / area 互斥（连 auto 都不行）
                payload["size"] = size
            else:
                if aspect_ratio and aspect_ratio != "auto":
                    payload["aspect_ratio"] = aspect_ratio
                elif kw.get("disable_prompt_enhanced"):
                    raise ValueError(
                        "H3-Image 关闭提示词增强（disable_prompt_enhanced）时，"
                        "必须给出 size（WxH）或具体的 aspect_ratio，不能用 auto。"
                    )
                payload["area"] = area

            if kw.get("disable_prompt_enhanced"):
                payload["disable_prompt_enhanced"] = True
        else:
            payload["response_format"] = kw.get("response_format") or "url"
            if payload["response_format"] == "b64_json":
                payload["response_format"] = "base64"
            payload["prompt_optimizer"] = bool(kw.get("prompt_optimizer", False))
            payload["aigc_watermark"] = bool(kw.get("aigc_watermark", False))

            if size:
                width, height = _parse_size(size)
                for v in (width, height):
                    if not 512 <= v <= 2048 or v % 8 != 0:
                        raise ValueError(
                            "image-01 的自定义尺寸必须在 512–2048 之间且是 8 的倍数。"
                        )
                payload["width"] = width
                payload["height"] = height
            else:
                # image-01 没有 auto 选项，auto 视作 1:1
                payload["aspect_ratio"] = "1:1" if aspect_ratio == "auto" else aspect_ratio

        # ---- 参考图 ----
        refs = cls._collect_references(kw, h3)
        if refs:
            if h3:
                payload["images"] = [{"image_url": r} for r in refs]
            else:
                payload["subject_reference"] = [{"type": "character", "image_file": refs[0]}]

        # ---- 风格（仅 image-01-live）----
        style_type = (kw.get("style_type") or "").strip()
        if style_type:
            if model != "image-01-live":
                raise ValueError("style 参数只有 image-01-live 支持。")
            payload["style"] = {
                "style_type": style_type,
                "style_weight": float(kw.get("style_weight", 0.8) or 0.8),
            }

        return payload

    @classmethod
    def _collect_references(cls, kw, h3: bool) -> list:
        """收集参考图：IMAGE 输入 + URL 输入（URL 支持逗号分隔）。"""
        refs: list[str] = []
        for key in ("reference_image", "reference_image_2", "reference_image_3",
                    "reference_image_4", "reference_image_5", "reference_image_6"):
            tensor = kw.get(key)
            if tensor is not None:
                refs.append(tensor_to_data_uri(tensor))
        url_field = (kw.get("reference_image_url") or "").strip()
        if url_field:
            for one in url_field.split(","):
                one = one.strip()
                if one:
                    refs.append(one)
        if refs and not h3 and len(refs) > 1:
            # 旧接口只支持一张。**不静默截断**——静默丢图会让人以为多图生效了。
            raise ValueError(
                f"image-01 的 subject_reference 官方只支持 1 张参考图，"
                f"本次收到 {len(refs)} 张。多图请改用 MiniMax-H3-Image（最多 16 张）。"
            )
        if refs and h3 and len(refs) > 16:
            raise ValueError("H3-Image 单次最多 16 张参考图。")
        return refs

    # ------------------------------------------------------------------ #
    # 请求
    # ------------------------------------------------------------------ #
    @classmethod
    def _endpoint(cls, model: str, has_refs: bool) -> str:
        if _is_h3_image(model):
            return "/v1/images/edits" if has_refs else "/v1/images/generations"
        return "/v1/image_generation"

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        model = payload.get("model", "")
        has_refs = bool(payload.get("images") or payload.get("subject_reference"))
        path = cls._endpoint(model, has_refs)
        timeout = H3_TIMEOUT if _is_h3_image(model) else 120.0
        resp = await request_json(session, PROVIDER, "POST", f"{base}{path}", headers, payload, timeout=timeout)

        if _is_h3_image(model):
            # 新接口：逐项检查，部分失败是常态
            failed = []
            for idx, item in enumerate(dig(resp, "data", default=[]) or []):
                err = dig(item, "error", default=None)
                if err:
                    failed.append(f"第 {idx + 1} 张：{err.get('message') or err}")
            if failed and not cls.results_of(resp):
                raise RuntimeError(
                    f"[{PROVIDER}] {model} 全部图片生成失败：\n  " + "\n  ".join(failed)
                )
            if failed:
                print(f"[{PROVIDER}] {model} 部分图片失败（不影响已成功的）：\n  " + "\n  ".join(failed))
            return resp

        # 旧接口：业务错误藏在 HTTP 200 的 base_resp 里
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
        """两种响应结构都要支持。"""
        # 新接口：data 是数组，每项 {url|b64_json}，失败项只有 error
        data = resp.get("data")
        if isinstance(data, list):
            out = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("url"):
                    out.append({"url": item["url"]})
                elif item.get("b64_json"):
                    out.append({"base64": item["b64_json"]})
            return out
        # 旧接口：data 是对象
        urls = dig(resp, "data", "image_urls", default=None)
        if urls:
            return [{"url": u} for u in urls]
        b64 = dig(resp, "data", "image_base64", default=None)
        if b64:
            return [{"base64": b} for b in b64]
        return []

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        usage = dig(resp, "usage", default=None)
        if isinstance(usage, dict) and usage:
            out = dict(usage)
            out["request_id"] = dig(resp, "request_id", default="")
            # 把实际用的提示词也带出来（对调参很有用）
            revised = []
            for item in dig(resp, "data", default=[]) or []:
                if isinstance(item, dict) and item.get("revised_prompt"):
                    revised.append(item["revised_prompt"])
            if revised:
                out["revised_prompt"] = revised[0]
            return out
        meta = dig(resp, "metadata", default={}) or {}
        return {
            "success_count": meta.get("success_count"),
            "failed_count": meta.get("failed_count"),
            "id": dig(resp, "id", default=""),
        }


def _parse_size(text: str) -> tuple:
    """'2720x1536' -> (2720, 1536)。"""
    raw = (text or "").replace("×", "x").replace("*", "x").strip()
    if "x" not in raw:
        raise ValueError(f"size 格式应为 宽x高，例如 2720x1536（收到 {text!r}）。")
    w, _, h = raw.partition("x")
    try:
        return int(w), int(h)
    except ValueError:
        raise ValueError(f"size 格式应为 宽x高，例如 2720x1536（收到 {text!r}）。") from None


class MiniMaxImageNode(CloudImageNodeBase):
    PROVIDER = PROVIDER
    KEY_ENV = MiniMaxImageProvider.KEY_ENV
    FILE_KEY = MiniMaxImageProvider.FILE_KEY
    DEFAULT_BASE_URL = MiniMaxImageProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = MiniMaxImageProvider.BASE_URL_HINT
    CATEGORY = "cloud/image/MiniMax"
    IMPL = MiniMaxImageProvider
    REQUEST_TIMEOUT = H3_TIMEOUT + 60

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (
                    MODELS,
                    {
                        "default": "MiniMax-H3-Image",
                        "tooltip": (
                            "MiniMax-H3-Image：新模型，支持 16 张参考图、16MP、提示词增强（默认开），"
                            "走 /v1/images/generations。\n"
                            "image-01 / image-01-live：旧接口 /v1/image_generation，"
                            "仅 1 张参考图，提示词 ≤1500 字符。"
                        ),
                    },
                ),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面描述。H3-Image ≤32000 字符，image-01 ≤1500。"},
                ),
            },
            "optional": {
                "size": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": (
                            "精确尺寸 宽x高，如 2720x1536。留空则按 aspect_ratio + area 自适应。\n"
                            "image-01：512–2048 且为 8 的倍数；H3-Image：面积 655,360–20,000,000 px，比例 1:3–3:1。"
                        ),
                    },
                ),
                "aspect_ratio": (
                    ASPECT_RATIOS,
                    {"default": "auto", "tooltip": "宽高比。auto = 由提示词增强自动决定。"},
                ),
                "area": (
                    AREAS,
                    {"default": "4K", "tooltip": "清晰度档，仅 H3-Image 生效。4K ≈ 4096×4096（16MP）。"},
                ),
                "n": ("INT", {"default": 1, "min": 1, "max": 10, "tooltip": "生成张数。"}),
                "seed": (
                    "INT",
                    {"default": 42, "min": 0, "max": 4294967295, "control_after_generate": True},
                ),
                "response_format": (
                    ["url", "base64"],
                    {
                        "default": "url",
                        "tooltip": "url 有效期 24 小时（本项目会立即下载到本地）；base64 直接内联返回。",
                    },
                ),
                "reference_image": ("IMAGE", {"tooltip": "参考图 1。"}),
                "reference_image_2": ("IMAGE", {"tooltip": "参考图 2。"}),
                "reference_image_3": ("IMAGE", {"tooltip": "参考图 3。"}),
                "reference_image_4": ("IMAGE", {"tooltip": "参考图 4。"}),
                "reference_image_5": ("IMAGE", {"tooltip": "参考图 5。"}),
                "reference_image_6": ("IMAGE", {"tooltip": "参考图 6。"}),
                "reference_image_url": (
                    "STRING",
                    {"default": "", "tooltip": "参考图 URL，多个用逗号分隔。H3-Image 最多 16 张。"},
                ),
                "output_format": (
                    ["", "jpeg", "png", "webp"],
                    {"default": "", "tooltip": "输出格式，仅 H3-Image 生效（默认 jpeg）。"},
                ),
                "output_compression": (
                    "INT",
                    {"default": 95, "min": 0, "max": 100, "tooltip": "压缩质量，仅 H3-Image 的 jpeg/webp 生效。"},
                ),
                "disable_prompt_enhanced": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": (
                            "关闭提示词增强（仅 H3-Image）。关闭后用原始提示词，"
                            "但必须给出 size 或具体 aspect_ratio。"
                        ),
                    },
                ),
                "prompt_optimizer": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "提示词优化，仅 image-01 系列生效。"},
                ),
                "aigc_watermark": ("BOOLEAN", {"default": False, "tooltip": "AIGC 水印，仅 image-01 系列生效。"}),
                "style_type": (
                    STYLE_TYPES + [""],
                    {"default": "", "tooltip": "风格预设，仅 image-01-live 支持。"},
                ),
                "style_weight": ("FLOAT", {"default": 0.8, "min": 0.01, "max": 1.0, "step": 0.05}),
                **cls.common_optional(),
            },
        }
