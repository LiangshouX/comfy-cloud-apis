"""MiniMax H3 —— 直连官方 V2 API。

契约（对齐 ComfyUI 官方节点 comfy_api_nodes/nodes_minimax.py 中
MinimaxHailuo03* 节点所依据的官方接口）：

    POST {base}/v2/video_generation                  -> {"task_id": "..."}
    GET  {base}/v2/query/video_generation/{task_id}  -> {"task": {"status": ..., "content": {"url": ...}}}

状态：queued / running / succeeded / failed / cancelled / expired
成片：task.content.url
用量：task.usage

注意：社区里流传的 /v1 接口是老的 Hailuo（T2V-01/I2V-01），**不是 H3**，
两套协议不可混用。本节点只实现 V2。
"""

from __future__ import annotations

from ..core.base import CloudTaskQueryNode, CloudVideoNodeBase
from ..core.http import dig, request_json
from ..core.media import tensor_to_data_uri
from ..core.task import normalize_status

PROVIDER = "MiniMax"

BASE_URL_CN = "https://api.minimax.chat"
BASE_URL_INTL = "https://api.minimaxi.chat"
BASE_URL_ALT = "https://api.minimax.io"

MODELS = ["MiniMax-H3", "MiniMax-H3-Max", "MiniMax-H3-Highspeed", "MiniMax-H3-Lite"]
RESOLUTIONS = ["768P", "2K"]
RATIOS = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]


class MiniMaxProvider:
    KEY_ENV = ("MINIMAX_API_KEY", "MINIMAX_TOKEN")
    FILE_KEY = "minimax"
    DEFAULT_BASE_URL = BASE_URL_CN
    BASE_URL_HINT = (
        "MiniMax 开放平台根域名。国内用 https://api.minimax.chat，国际用 https://api.minimaxi.chat。"
        "本节点走 V2 路径，不要带 /v1。"
    )

    @classmethod
    def normalize_base_url(cls, raw: str) -> str:
        base = (raw or "").strip().rstrip("/")
        if base.endswith("/v1"):  # 兼容用户直接粘贴 V1 风格地址
            base = base[:-3]
        return base

    @classmethod
    def build_payload(cls, **kw) -> dict:
        prompt = (kw.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt 不能为空。")
        duration = int(kw.get("duration", 5))
        if not 4 <= duration <= 15:
            raise ValueError("duration 必须在 4–15 秒之间。")

        soundscape = (kw.get("overall_soundscape") or "").strip()
        music = (kw.get("non_diegetic_music") or "").strip()
        if kw.get("use_structured_fields", True):
            parts = ["integrated_multimodal_description: " + prompt]
            if soundscape:
                parts.append("overall_soundscape: " + soundscape)
            if music:
                parts.append("non_diegetic_music: " + music)
            final_prompt = "\n".join(parts)
        else:
            final_prompt = prompt

        first_frame = kw.get("first_frame")
        last_frame = kw.get("last_frame")
        first_url = (kw.get("first_frame_url") or "").strip()
        last_url = (kw.get("last_frame_url") or "").strip()
        ref_images = [t for t in (kw.get("reference_image_1"), kw.get("reference_image_2"), kw.get("reference_image_3")) if t is not None]
        ref_video = (kw.get("reference_video_url") or "").strip()
        ref_audio = (kw.get("reference_audio_url") or "").strip()

        frame_roles = []
        if first_frame is not None or first_url:
            frame_roles.append("first_frame")
        if last_frame is not None or last_url:
            frame_roles.append("last_frame")
        ref_roles = []
        if ref_images:
            ref_roles.append("reference_image")
        if ref_video:
            ref_roles.append("reference_video")
        if ref_audio:
            ref_roles.append("reference_audio")

        if frame_roles and ref_roles:
            raise ValueError(
                "首尾帧（first_frame/last_frame）与多模态参考（reference_*）属于互斥请求族，"
                "官方不允许混用，请拆成两次生成。"
            )
        if ref_roles and not (ref_images or ref_video):
            raise ValueError("参考音频必须与至少一张参考图或一段参考视频同时提供。")

        content = [{"type": "text", "text": final_prompt}]

        def add_image(url: str, role: str):
            content.append({"type": "image_url", "image_url": {"url": url}, "role": role})

        if first_frame is not None or first_url:
            add_image(first_url or tensor_to_data_uri(first_frame), "first_frame")
        if last_frame is not None or last_url:
            add_image(last_url or tensor_to_data_uri(last_frame), "last_frame")
        for img in ref_images:
            add_image(tensor_to_data_uri(img), "reference_image")
        if ref_video:
            content.append({"type": "video_url", "video_url": {"url": ref_video}, "role": "reference_video"})
        if ref_audio:
            content.append({"type": "audio_url", "audio_url": {"url": ref_audio}, "role": "reference_audio"})

        ratio = kw.get("ratio", "adaptive")
        return {
            "model": kw.get("model", "MiniMax-H3"),
            "content": content,
            "resolution": kw.get("resolution", "768P"),
            "duration": duration,
            "ratio": None if ratio == "adaptive" else ratio,
            "seed": int(kw.get("seed", 0) or 0),
            "aigc_watermark": bool(kw.get("aigc_watermark", False)),
        }

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> str:
        resp = await request_json(session, PROVIDER, "POST", f"{base}/v2/video_generation", headers, payload)
        return resp.get("task_id") or ""

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await request_json(session, PROVIDER, "GET", f"{base}/v2/query/video_generation/{task_id}", headers)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return normalize_status(dig(resp, "task", "status"))

    @classmethod
    def video_url_of(cls, resp: dict) -> str:
        return dig(resp, "task", "content", "url", default="") or ""

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return dig(resp, "task", "usage", default={}) or {}


class MiniMaxH3Node(CloudVideoNodeBase):
    IMPL = MiniMaxProvider
    PROVIDER = PROVIDER
    KEY_ENV = MiniMaxProvider.KEY_ENV
    FILE_KEY = MiniMaxProvider.FILE_KEY
    DEFAULT_BASE_URL = MiniMaxProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = MiniMaxProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/MiniMax"

    @classmethod
    def INPUT_TYPES(cls):
        spec = {
            "required": {
                **cls.common_required(),
                "model": (MODELS, {"default": "MiniMax-H3"}),
                "prompt": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "画面 / 主体 / 动作 / 运镜。"},
                ),
                "resolution": (RESOLUTIONS, {"default": "768P"}),
                "duration": ("INT", {"default": 5, "min": 4, "max": 15, "step": 1}),
                "ratio": (RATIOS, {"default": "adaptive"}),
                "seed": (
                    "INT",
                    {"default": 42, "min": 0, "max": 4294967295, "control_after_generate": True},
                ),
            },
            "optional": {
                "overall_soundscape": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "环境音与动作音，建议写。"},
                ),
                "non_diegetic_music": (
                    "STRING",
                    {"multiline": True, "default": "", "tooltip": "配乐描述。"},
                ),
                "first_frame": ("IMAGE", {"tooltip": "首帧图。与 reference_* 不能混用。"}),
                "last_frame": ("IMAGE", {"tooltip": "尾帧图。"}),
                "first_frame_url": (
                    "STRING",
                    {"default": "", "tooltip": "首帧图 URL（填了则忽略 first_frame）。大图建议走 URL。"},
                ),
                "last_frame_url": ("STRING", {"default": "", "tooltip": "尾帧图 URL。"}),
                "reference_image_1": ("IMAGE", {"tooltip": "参考图 1。"}),
                "reference_image_2": ("IMAGE", {"tooltip": "参考图 2。"}),
                "reference_image_3": ("IMAGE", {"tooltip": "参考图 3。"}),
                "reference_video_url": ("STRING", {"default": "", "tooltip": "参考视频 URL（2–15 秒）。"}),
                "reference_audio_url": ("STRING", {"default": "", "tooltip": "参考音频 URL（2–15 秒，只带音色）。"}),
                "aigc_watermark": ("BOOLEAN", {"default": False, "tooltip": "是否加 AIGC 水印。"}),
                "use_structured_fields": (
                    "BOOLEAN",
                    {"default": True, "tooltip": "按官方三段式拼装提示词。"},
                ),
                **cls.common_optional(),
            },
        }
        return spec


class MiniMaxH3TaskQueryNode(CloudTaskQueryNode):
    IMPL = MiniMaxProvider
    PROVIDER = PROVIDER
    KEY_ENV = MiniMaxProvider.KEY_ENV
    FILE_KEY = MiniMaxProvider.FILE_KEY
    DEFAULT_BASE_URL = MiniMaxProvider.DEFAULT_BASE_URL
    BASE_URL_HINT = MiniMaxProvider.BASE_URL_HINT
    CATEGORY = "cloud/video/MiniMax"

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await MiniMaxProvider.fetch(session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return MiniMaxProvider.status_of(resp)
