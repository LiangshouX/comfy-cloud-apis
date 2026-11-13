"""Seedance（豆包）—— 直连火山方舟 Ark。

契约（官方文档 https://docs.volcengine.com/docs/82379/2298881）：

    POST {base}/contents/generations/tasks   -> {"id": "<TASK_ID>"}
    GET  {base}/contents/generations/tasks/{id}
        -> {"id":..., "status": "succeeded", "content": {"video_url": "..."}, "usage": {...}}

默认 base：https://ark.cn-beijing.volces.com/api/v3
鉴权：Authorization: Bearer $ARK_API_KEY

**关于 content.video_url 的形态**：官方文档在不同版本里出现过
`"content": {"video_url": "<URL>"}`（对象）与 `content.video_url`（裸字符串）
两种写法，这里用容错取值，两种都支持。

**关于图片**：官方示例一律用公网 URL。data URI 未被明确承诺，
所以默认优先用 URL；只有没有 URL 时才退回内联 base64，并打印警告。
"""

from __future__ import annotations

from ..core.base import CloudTaskQueryNode, CloudVideoNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri
from ..core.task import normalize_status

PROVIDER = "Seedance"

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

MODELS = [
    "doubao-seedance-2-5-260628",
    "doubao-seedance-2-0-260128",
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-2-0-mini-260615",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedance-1-0-pro-fast-251015",
]
RESOLUTIONS = ["480p", "720p", "1080p", "4k"]
RATIOS = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]


class SeedanceProvider:
    KEY_ENV = ("ARK_API_KEY", "VOLCENGINE_API_KEY")
    FILE_KEY = "seedance"
    DEFAULT_BASE_URL = BASE_URL
    BASE_URL_HINT = (
        "火山方舟 API 根地址，形如 https://ark.cn-beijing.volces.com/api/v3。"
        "model 必须是**你在方舟控制台创建过推理接入点**的模型 ID。"
    )

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        content = [{"type": "text", "text": prompt}]

        def add_image(url: str, role: str):
            content.append({"type": "image_url", "image_url": {"url": url}, "role": role})

        first = kw.get("first_frame")
        last = kw.get("last_frame")
        first_url = (kw.get("first_frame_url") or "").strip()
        last_url = (kw.get("last_frame_url") or "").strip()
        ref_images = [t for t in (kw.get("reference_image_1"), kw.get("reference_image_2"), kw.get("reference_image_3")) if t is not None]
        ref_video = (kw.get("reference_video_url") or "").strip()
        ref_audio = (kw.get("reference_audio_url") or "").strip()

        if first is not None or first_url:
            if first_url:
                add_image(first_url, "first_frame")
            else:
                print("[Seedance] 注意：官方示例均使用公网 URL，内联 base64 可能不被接受。")
                add_image(tensor_to_data_uri(first), "first_frame")
        if last is not None or last_url:
            if last_url:
                add_image(last_url, "last_frame")
            else:
                print("[Seedance] 注意：官方示例均使用公网 URL，内联 base64 可能不被接受。")
                add_image(tensor_to_data_uri(last), "last_frame")
        for img in ref_images:
            print("[Seedance] 注意：官方示例均使用公网 URL，内联 base64 可能不被接受。")
            add_image(tensor_to_data_uri(img), "reference_image")
        if ref_video:
            content.append({"type": "video_url", "video_url": {"url": ref_video}, "role": "reference_video"})
        if ref_audio:
            content.append({"type": "audio_url", "audio_url": {"url": ref_audio}, "role": "reference_audio"})

        ratio = kw.get("ratio", "adaptive")
        payload = {
            "model": kw.get("model", "doubao-seedance-2-0-fast-260128"),
            "content": content,
            "generate_audio": bool(kw.get("generate_audio", True)),
            "ratio": None if ratio == "adaptive" else ratio,
            "duration": int(kw.get("duration", 5) or 5),
            "watermark": bool(kw.get("watermark", False)),
        }
        resolution = (kw.get("resolution") or "").strip()
        if resolution:
            payload["resolution"] = resolution
        seed = kw.get("seed")
        if seed is not None and int(seed) >= 0:
            payload["seed"] = int(seed)
        if kw.get("camera_fixed") is not None:
            payload["camera_fixed"] = bool(kw.get("camera_fixed"))
        if kw.get("service_tier"):
            payload["service_tier"] = kw.get("service_tier")
        return payload

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> str:
        resp = await request_json(session, PROVIDER, "POST", f"{base}/contents/generations/tasks", headers, payload)
        return resp.get("id") or resp.get("task_id") or ""

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await request_json(session, PROVIDER, "GET", f"{base}/contents/generations/tasks/{task_id}", headers)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return normalize_status(dig(resp, "status"))

    @classmethod
    def video_url_of(cls, resp: dict) -> str:
        # 兼容两种形态：content 是个 dict 或 content 本身就是字符串
        url = dig(resp, "content", "video_url", default="")
        if not url:
            content = resp.get("content")
            if isinstance(content, str):
                url = content
            elif isinstance(content, dict):
                url = content.get("video_url") or content.get("url") or ""
        if not url:
            url = dig(resp, "video_url", default="") or ""
        return url or ""

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "usage", default={}) or {}


class SeedanceNode(CloudVideoNodeBase):
    IMPL = SeedanceProvider
    PROVIDER = PROVIDER
    KEY_ENV = SeedanceProvider.KEY_ENV
    FILE_KEY = SeedanceProvider.FILE_KEY
    DEFAULT_BASE_URL = SeedanceProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = SeedanceProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/Seedance"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "doubao-seedance-2-0-fast-260128"}),
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "画面 / 动作 / 运镜。"}),
                "duration": ("INT", {"default": 5, "min": 2, "max": 15, "step": 1}),
                "ratio": (RATIOS, {"default": "adaptive"}),
                "resolution": (RESOLUTIONS, {"default": "720p"}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧图。官方建议改用 first_frame_url。"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧图。"}),
                "first_frame_url": ("STRING", {"default": "", "tooltip": "首帧图公网 URL（推荐）。"}),
                "last_frame_url": ("STRING", {"default": "", "tooltip": "尾帧图公网 URL。"}),
                "reference_image_1": ("IMAGE", {"tooltip": "参考图 1。"}),
                "reference_image_2": ("IMAGE", {"tooltip": "参考图 2。"}),
                "reference_image_3": ("IMAGE", {"tooltip": "参考图 3。"}),
                "reference_video_url": ("STRING", {"default": "", "tooltip": "参考视频 URL。"}),
                "reference_audio_url": ("STRING", {"default": "", "tooltip": "参考音频 URL。"}),
                "generate_audio": ("BOOLEAN", {"default": True, "tooltip": "是否生成音轨。"}),
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "是否加水印。"}),
                "camera_fixed": ("BOOLEAN", {"default": False, "tooltip": "固定摄像头。"}),
                "service_tier": (["default", "flex"], {"default": "default", "tooltip": "flex = 离线推理，通常半价。"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 4294967295, "control_after_generate": True}),
                **cls.common_optional(),
            },
        }


class SeedanceTaskQueryNode(CloudTaskQueryNode):
    IMPL = SeedanceProvider
    PROVIDER = PROVIDER
    KEY_ENV = SeedanceProvider.KEY_ENV
    FILE_KEY = SeedanceProvider.FILE_KEY
    DEFAULT_BASE_URL = SeedanceProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = SeedanceProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/Seedance"

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await SeedanceProvider.fetch(session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return SeedanceProvider.status_of(resp)
