"""测试夹具：stub 掉 ComfyUI 专属依赖，让本仓库能在纯 Python 环境里跑测试。

ComfyUI 运行时自带 folder_paths / comfy_api / aiohttp / torch，
CI 里会装 aiohttp+torch(cpu)，这里只 stub ComfyUI 私有的两个模块。
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- folder_paths ---
fp = types.ModuleType("folder_paths")
fp.get_output_directory = lambda: os.path.join(ROOT, ".tmp_output")
fp.get_temp_directory = lambda: os.path.join(ROOT, ".tmp_temp")
fp.get_user_directory = lambda: os.path.join(ROOT, ".tmp_user")
sys.modules["folder_paths"] = fp

# --- comfy_api.latest ---
comfy_api = types.ModuleType("comfy_api")
latest = types.ModuleType("comfy_api.latest")


class VideoFromFile:
    def __init__(self, file, **kwargs):
        self.file = file


class InputImpl:
    VideoFromFile = VideoFromFile


latest.InputImpl = InputImpl
latest.VideoFromFile = VideoFromFile
comfy_api.latest = latest
sys.modules["comfy_api"] = comfy_api
sys.modules["comfy_api.latest"] = latest


# --- aiohttp：CI 里会装真实依赖；本地没装时用 stub 顶掉 ---
try:  # pragma: no cover
    import aiohttp  # noqa: F401
except Exception:  # pragma: no cover
    aiohttp = types.ModuleType("aiohttp")

    class _Timeout:
        def __init__(self, *args, **kwargs):
            pass

    class _Session:
        pass

    aiohttp.ClientSession = _Session
    aiohttp.ClientTimeout = _Timeout
    aiohttp.FormData = _Session
    sys.modules["aiohttp"] = aiohttp
