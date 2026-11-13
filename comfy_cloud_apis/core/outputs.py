"""ComfyUI 输出类型封装（VIDEO / IMAGE / AUDIO）。

官方 API 节点用的是 `comfy_api.latest.InputImpl.VideoFromFile`；
这里保持一致，使本项目产出的节点可以与官方节点互换使用。
"""

from __future__ import annotations

import io
import os
from typing import Any


def video_output(source: str | io.BytesIO):
    """把本地 mp4 路径（或字节流）包装成 ComfyUI 的 VIDEO 类型。"""
    try:
        from comfy_api.latest import InputImpl

        return InputImpl.VideoFromFile(source)
    except Exception:
        pass
    try:
        from comfy_api.latest import VideoFromFile

        return VideoFromFile(source)
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "当前 ComfyUI 版本不支持 VIDEO 输出类型，请升级 ComfyUI 后重试。"
            + (f"（成片已保存到 {source}）" if isinstance(source, str) else "")
        ) from exc


def image_output(image_bytes: bytes):
    """图片字节 -> ComfyUI 的 IMAGE 类型（torch tensor）。"""
    from .media import bytes_to_tensor

    return bytes_to_tensor(image_bytes, mode="RGB")


def audio_output(audio_bytes: bytes) -> dict:
    """音频字节 -> ComfyUI 的 AUDIO 类型 {"waveform", "sample_rate"}。"""
    import av
    import torch

    with av.open(io.BytesIO(audio_bytes)) as af:
        if not af.streams.audio:
            raise ValueError("响应中没有音频流。")
        stream = af.streams.audio[0]
        sample_rate = int(stream.codec_context.sample_rate)
        n_channels = stream.channels or 1
        frames = []
        for frame in af.decode(streams=stream.index):
            arr = frame.to_ndarray()
            buf = torch.from_numpy(arr)
            if buf.ndim == 1:
                buf = buf.unsqueeze(0)
            elif buf.shape[0] != n_channels and buf.shape[-1] == n_channels:
                buf = buf.transpose(0, 1).contiguous()
            elif buf.shape[0] != n_channels:
                buf = buf.reshape(-1, n_channels).t().contiguous()
            frames.append(buf)
    if not frames:
        raise ValueError("解码出 0 个音频帧。")
    wav = torch.cat(frames, dim=1)
    if wav.dtype == torch.int16:
        wav = wav.float() / (2 ** 15)
    elif wav.dtype == torch.int32:
        wav = wav.float() / (2 ** 31)
    return {"waveform": wav.unsqueeze(0).contiguous(), "sample_rate": sample_rate}
