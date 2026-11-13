"""通义万相 Wan（阿里云百炼 DashScope）—— 直连官方 API。

契约（官方文档 https://help.aliyun.com/zh/model-studio/video-generation-api-reference）：

    POST {base}/api/v1/services/aigc/video-generation/video-synthesis
         Header: X-DashScope-Async: enable   ← 必须，否则报 "does not support synchronous calls"
         -> {"output": {"task_id": "...", "task_status": "PENDING"}}
    GET  {base}/api/v1/tasks/{task_id}
         -> {"output": {"task_status": "SUCCEEDED", "video_url": "..."}, "usage": {...}}

默认 base（北京地域）：https://dashscope.aliyuncs.com
国际（新加坡）：https://dashscope-intl.aliyuncs.com
业务空间专属域名：https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com

**两个重要特性**：
1. 官方明确支持**内联 base64 图片**（`data:{MIME};base64,{...}`），
   所以本地图片不需要先传到图床——这是三家里唯一明确支持内联的。
2. task_id 与 video_url **有效期只有 24 小时**，所以必须立刻下载（本项目会自动下载）。

**响应结构有两种**：较新版本是 `{"output": {"task_status": ..., "video_url": ...}}`，
较旧版本是顶层 `{"status": "SUCCEEDED", "video_url": ...}`。这里两种都兼容。
"""

from __future__ import annotations

from ..core.base import CloudTaskQueryNode, CloudVideoNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri
from ..core.task import normalize_status

PROVIDER = "Qwen/Wan"

BASE_URL_CN = "https://dashscope.aliyuncs.com"
BASE_URL_INTL = "https://dashscope-intl.aliyuncs.com"

MODELS = [
    "wan2.6-t2v",
    "wan2.6-i2v",
    "wan2.6-i2v-flash",
    "wan2.6-r2v",
    "wan2.6-r2v-flash",
]

# 常用分辨率（size 必须是 宽*高，且按宽高比成对给出）
SIZES = [
    "1280*720",   # 16:9 720P
    "720*1280",   # 9:16
    "960*960",    # 1:1
    "1088*832",   # 4:3
    "832*1088",   # 3:4
    "1920*1080",  # 16:9 1080P
    "1080*1920",  # 9:16 1080P
    "1440*1440",  # 1:1 1080P
]


class QwenWanProvider:
    KEY_ENV = ("DASHSCOPE_API_KEY", "QWEN_API_KEY")
    FILE_KEY = "qwen"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "百炼 API 根域名。北京用 https://dashscope.aliyuncs.com，"
        "新加坡用 https://dashscope-intl.aliyuncs.com；"
        "使用业务空间专属域名时形如 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com。"
        "**模型、域名、API Key 必须属于同一地域。**"
    )

    @classmethod
    def extra_headers(cls) -> dict:
        # 缺这个头会直接报 "current user api does not support synchronous calls"
        return {"X-DashScope-Async": "enable"}

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")

        inp: dict = {"prompt": prompt}
        negative = (kw.get("negative_prompt") or "").strip()
        if negative:
            inp["negative_prompt"] = negative

        image = kw.get("first_frame")
        image_url = (kw.get("first_frame_url") or "").strip()
        if image is not None or image_url:
            # 百炼官方明确支持内联 base64
            inp["img_url"] = image_url or tensor_to_data_uri(image)

        audio_url = (kw.get("audio_url") or "").strip()
        if audio_url:
            inp["audio_url"] = audio_url

        ref_urls = []
        for key in ("reference_url_1", "reference_url_2", "reference_url_3", "reference_url_4", "reference_url_5"):
            val = (kw.get(key) or "").strip()
            if val:
                ref_urls.append(val)
        if ref_urls:
            inp["reference_urls"] = ref_urls

        params: dict = {}
        size = (kw.get("size") or "").strip()
        if size:
            params["size"] = size
        resolution = (kw.get("resolution") or "").strip()
        if resolution:
            params["resolution"] = resolution
        params["duration"] = int(kw.get("duration", 5) or 5)
        if kw.get("prompt_extend") is not None:
            params["prompt_extend"] = bool(kw.get("prompt_extend"))
        if kw.get("audio") is not None:
            params["audio"] = bool(kw.get("audio"))
        if kw.get("shot_type"):
            params["shot_type"] = kw.get("shot_type")
        if kw.get("watermark") is not None:
            params["watermark"] = bool(kw.get("watermark"))
        seed = kw.get("seed")
        if seed is not None and int(seed) >= 0:
            params["seed"] = int(seed)

        return {"model": kw.get("model", "wan2.6-i2v-flash"), "input": inp, "parameters": params}

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> str:
        resp = await request_json(
            session,
            PROVIDER,
            "POST",
            f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
            headers,
            payload,
        )
        return dig(resp, "output", "task_id", default="") or resp.get("task_id") or ""

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await request_json(session, PROVIDER, "GET", f"{base}/api/v1/tasks/{task_id}", headers)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        raw = dig(resp, "output", "task_status", default="") or resp.get("status") or ""
        return normalize_status(raw)

    @classmethod
    def video_url_of(cls, resp: dict) -> str:
        url = dig(resp, "output", "video_url", default="") or resp.get("video_url") or ""
        return url or ""

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "usage", default={}) or {}


class QwenWanNode(CloudVideoNodeBase):
    IMPL = QwenWanProvider
    PROVIDER = PROVIDER
    KEY_ENV = QwenWanProvider.KEY_ENV
    FILE_KEY = QwenWanProvider.FILE_KEY
    DEFAULT_BASE_URL = QwenWanProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = QwenWanProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/Qwen"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "wan2.6-i2v-flash"}),
                "prompt": ("STRING", {"multiline": True, "default": "", "tooltip": "画面 / 动作 / 运镜。"}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 15, "step": 1}),
                "size": (SIZES, {"default": "1280*720", "tooltip": "分辨率，格式 宽*高。直接影响价格。"}),
            },
            "optional": {
                "first_frame": ("IMAGE", {"tooltip": "首帧图。百炼官方支持内联 base64，无需图床。"}),
                "first_frame_url": ("STRING", {"default": "", "tooltip": "首帧图公网 URL（填了则忽略 first_frame）。"}),
                "audio_url": ("STRING", {"default": "", "tooltip": "参考音频 URL。"}),
                "negative_prompt": ("STRING", {"default": "", "tooltip": "反向提示词（万相支持，H3 不支持）。"}),
                "reference_url_1": ("STRING", {"default": "", "tooltip": "参考素材 URL 1（参考生视频用）。"}),
                "reference_url_2": ("STRING", {"default": "", "tooltip": "参考素材 URL 2。"}),
                "reference_url_3": ("STRING", {"default": "", "tooltip": "参考素材 URL 3。"}),
                "reference_url_4": ("STRING", {"default": "", "tooltip": "参考素材 URL 4。"}),
                "reference_url_5": ("STRING", {"default": "", "tooltip": "参考素材 URL 5。"}),
                "resolution": (
                    ["", "720P", "1080P"],
                    {"default": "", "tooltip": "可选分辨率档位；与 size 二选一。"},
                ),
                "prompt_extend": ("BOOLEAN", {"default": True, "tooltip": "提示词智能改写。"}),
                "audio": ("BOOLEAN", {"default": True, "tooltip": "是否生成有声视频（仅部分模型支持）。"}),
                "shot_type": (["", "single", "multi"], {"default": "", "tooltip": "单镜头 / 多镜头叙事。"}),
                "watermark": ("BOOLEAN", {"default": False, "tooltip": "是否加「AI生成」水印。"}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647, "control_after_generate": True}),
                **cls.common_optional(),
            },
        }


class QwenWanTaskQueryNode(CloudTaskQueryNode):
    IMPL = QwenWanProvider
    PROVIDER = PROVIDER
    KEY_ENV = QwenWanProvider.KEY_ENV
    FILE_KEY = QwenWanProvider.FILE_KEY
    DEFAULT_BASE_URL = QwenWanProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = QwenWanProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/Qwen"

    @classmethod
    def extra_headers(cls) -> dict:
        return QwenWanProvider.extra_headers()

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await QwenWanProvider.fetch(session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return QwenWanProvider.status_of(resp)
