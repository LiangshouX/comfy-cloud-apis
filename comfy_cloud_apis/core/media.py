"""媒体处理：图像 tensor 互转、文件落盘、目录管理。"""

from __future__ import annotations

import base64
import io
import os
import time
from typing import Optional

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


def output_root() -> str:
    if folder_paths:
        return folder_paths.get_output_directory()
    return os.path.join(os.getcwd(), "output")


def temp_root() -> str:
    if folder_paths:
        return folder_paths.get_temp_directory()
    return os.path.join(os.getcwd(), "temp")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def provider_dir(provider: str, to_output: bool = True) -> str:
    root = output_root() if to_output else temp_root()
    return ensure_dir(os.path.join(root, "comfy_cloud_apis", provider.lower()))


def tensor_to_data_uri(image_tensor: Optional[torch.Tensor], mime: str = "image/png") -> str:
    """[B,H,W,C] float tensor -> data URI。

    哪些厂商接受内联 base64：
      * DashScope（通义万相）：官方明确支持 `data:{MIME};base64,{...}`
      * Seedance / MiniMax：文档建议用公网 URL，内联 base64 未明确承诺
    因此默认策略是**优先用 URL**，URL 缺失时才退回内联。
    """
    if image_tensor is None:
        return ""
    import numpy as np

    t = image_tensor
    if len(t.shape) == 4:
        t = t[0]
    arr = (t.detach().cpu().numpy() * 255.0).astype(np.uint8)
    img = Image.fromarray(arr)
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def bytes_to_tensor(image_bytes: bytes, mode: str = "RGBA"):
    """原始图片字节 -> [1,H,W,C] float32 tensor。"""
    import numpy as np
    import torch
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert(mode)
    arr = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def timestamped_name(prefix: str, ext: str = ".mp4") -> str:
    return f"{prefix}_{time.strftime('%Y%m%d-%H%M%S')}{ext}"
