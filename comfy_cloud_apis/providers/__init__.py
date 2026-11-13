"""各厂商实现。新增一家 = 在这里加一行导出。"""

from .minimax import MiniMaxH3Node, MiniMaxH3TaskQueryNode
from .minimax_image import MiniMaxImageNode
from .qwen_image import QwenImageNode
from .qwen_wan import QwenWanNode, QwenWanTaskQueryNode
from .seedance import SeedanceNode, SeedanceTaskQueryNode
from .seedream import SeedreamImageNode
from .wan_image import WanImageNode, WanImageTaskQueryNode

__all__ = [
    # 视频
    "MiniMaxH3Node",
    "MiniMaxH3TaskQueryNode",
    "SeedanceNode",
    "SeedanceTaskQueryNode",
    "QwenWanNode",
    "QwenWanTaskQueryNode",
    # 生图
    "MiniMaxImageNode",
    "SeedreamImageNode",
    "QwenImageNode",
    "WanImageNode",
    "WanImageTaskQueryNode",
]
