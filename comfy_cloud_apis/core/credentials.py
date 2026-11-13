"""凭据解析：节点输入 → 环境变量 → 配置文件。

安全原则（贯穿整个项目）：
1. **API Key 绝不写进工作流 JSON**。节点里的 api_key 输入框留空时，
   自动回退到环境变量；只有用户显式填写才会明文落盘。
2. 每次解析都会返回 key 的**来源**，节点可以在控制台打印，
   方便用户确认到底用的是哪个来源。
3. 日志中永远不打印 key 本身。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Sequence

# ComfyUI 的 user 目录（用于可选的本地配置文件）
try:
    import folder_paths

    _USER_DIR = folder_paths.get_user_directory()
except Exception:  # pragma: no cover
    _USER_DIR = os.path.join(os.path.expanduser("~"), ".comfyui")

CREDENTIALS_FILE = os.path.join(_USER_DIR, "comfy_cloud_apis_credentials.json")


@dataclass
class ResolvedKey:
    key: str
    source: str  # "node" | "env:MINIMAX_API_KEY" | "file:comfy_cloud_apis_credentials.json"

    def describe(self) -> str:
        return f"API Key 来源：{self.source}"


def _load_credential_file() -> dict:
    """读取可选的本地凭据文件（默认不存在，且已在 .gitignore 中）。"""
    try:
        if not os.path.isfile(CREDENTIALS_FILE):
            return {}
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_key(
    node_key: str,
    env_names: Sequence[str],
    file_key: Optional[str] = None,
    provider_label: str = "provider",
) -> ResolvedKey:
    """按优先级解析 API Key：节点输入 > 环境变量 > 凭据文件。"""
    node_key = (node_key or "").strip()
    if node_key:
        return ResolvedKey(node_key, "node")

    for name in env_names:
        val = os.environ.get(name, "").strip()
        if val:
            return ResolvedKey(val, f"env:{name}")

    if file_key:
        val = str(_load_credential_file().get(file_key, "") or "").strip()
        if val:
            return ResolvedKey(val, "file:comfy_cloud_apis_credentials.json")

    raise ValueError(
        f"[{provider_label}] 缺少 API Key。\n"
        f"  方法一（推荐）：在节点 api_key 输入框留空，设置环境变量 "
        f"{' 或 '.join(env_names)} 后重启 ComfyUI。\n"
        f"  方法二：在节点 api_key 输入框直接填写（注意：会被明文保存进工作流 JSON）。\n"
        f"  方法三：在 {CREDENTIALS_FILE} 里写入 {{\"{file_key or env_names[0]}\": \"...\"}}。"
    )


def env_var_hint(env_names: Sequence[str]) -> str:
    return " / ".join(env_names)
