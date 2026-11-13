"""ComfyUI · comfy-cloud-apis

把各家云端视频/图像 API 封装成 ComfyUI 原生节点：
请求直连厂商官方域名，不经过任何第三方代理；API Key 可走环境变量，
不会被写进导出的工作流 JSON。

安装：
    cd ComfyUI/custom_nodes
    git clone https://github.com/LiangshouX/comfy-cloud-apis.git
    # 重启 ComfyUI

节点出现在分类 cloud/video/* 与 cloud/image/* 下。

所有推理都在云端完成，本地只做节点编排与文件收发，
因此**没有 GPU 的机器同样可以运行**（ComfyUI 加 --cpu 启动即可）。
"""

from .comfy_cloud_apis.providers.minimax import MiniMaxH3Node, MiniMaxH3TaskQueryNode
from .comfy_cloud_apis.providers.minimax_image import MiniMaxImageNode
from .comfy_cloud_apis.providers.qwen_image import QwenImageNode
from .comfy_cloud_apis.providers.qwen_wan import QwenWanNode, QwenWanTaskQueryNode
from .comfy_cloud_apis.providers.seedance import SeedanceNode, SeedanceTaskQueryNode
from .comfy_cloud_apis.providers.seedream import SeedreamImageNode
from .comfy_cloud_apis.providers.wan_image import WanImageNode, WanImageTaskQueryNode

NODE_CLASS_MAPPINGS = {
    # ---- 视频 ----
    "CloudVideo_MiniMaxH3": MiniMaxH3Node,
    "CloudVideo_MiniMaxH3TaskQuery": MiniMaxH3TaskQueryNode,
    "CloudVideo_Seedance": SeedanceNode,
    "CloudVideo_SeedanceTaskQuery": SeedanceTaskQueryNode,
    "CloudVideo_QwenWan": QwenWanNode,
    "CloudVideo_QwenWanTaskQuery": QwenWanTaskQueryNode,
    # ---- 图像 ----
    "CloudImage_MiniMax": MiniMaxImageNode,
    "CloudImage_Seedream": SeedreamImageNode,
    "CloudImage_Qwen": QwenImageNode,
    "CloudImage_WanT2I": WanImageNode,
    "CloudImage_WanT2ITaskQuery": WanImageTaskQueryNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CloudVideo_MiniMaxH3": "MiniMax H3 生视频（官方 API 直连）",
    "CloudVideo_MiniMaxH3TaskQuery": "MiniMax H3 任务查询",
    "CloudVideo_Seedance": "Seedance 生视频（官方 API 直连）",
    "CloudVideo_SeedanceTaskQuery": "Seedance 任务查询",
    "CloudVideo_QwenWan": "通义万相 Wan 生视频（官方 API 直连）",
    "CloudVideo_QwenWanTaskQuery": "通义万相 任务查询",
    "CloudImage_MiniMax": "MiniMax image-01 生图（官方 API 直连）",
    "CloudImage_Seedream": "Seedream 即梦 生图（官方 API 直连）",
    "CloudImage_Qwen": "千问 Qwen-Image 生图（官方 API 直连）",
    "CloudImage_WanT2I": "通义万相 Wan 文生图（官方 API 直连，异步）",
    "CloudImage_WanT2ITaskQuery": "通义万相 生图任务查询",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
