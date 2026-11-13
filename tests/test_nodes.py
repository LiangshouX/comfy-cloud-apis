"""节点级回归测试：保证**每个注册出去的节点类**都能真正跑起来。

这一组测试是从一次真实 bug 里补上的：provider 类的方法写对了，
但节点类忘了把 provider 接到基类的钩子上，导致节点运行到一半才抛
NotImplementedError —— 而只测 provider 类的用例完全发现不了。

所以这里测的是**节点类本身**，而不是 provider 类。
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_plugin():
    """把仓库根目录当作插件包加载（ComfyUI 里也是这么加载的）。"""
    name = "comfy_cloud_apis_plugin"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "__init__.py"), submodule_search_locations=[ROOT]
    )
    mod = importlib.util.module_from_spec(spec)
    # 根 __init__.py 用的是相对 import，必须让包上下文正确
    mod.__package__ = name
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PLUGIN = _load_plugin()
GENERATION_NODES = [k for k in PLUGIN.NODE_CLASS_MAPPINGS if not k.endswith("TaskQuery")]


def _minimal_kwargs(node_cls) -> dict:
    """从 INPUT_TYPES 里推出最小可用参数集。"""
    spec = node_cls.INPUT_TYPES()
    kwargs = {}
    for name, cfg in (spec.get("required") or {}).items():
        if name in ("api_key", "base_url"):
            continue
        typ = cfg[0]
        opts = cfg[1] if len(cfg) > 1 and isinstance(cfg[1], dict) else {}
        if isinstance(typ, list):
            kwargs[name] = opts.get("default") or typ[0]
        elif typ == "STRING":
            kwargs[name] = opts.get("default") or ""
        elif typ == "INT":
            kwargs[name] = opts.get("default", 1)
        elif typ == "FLOAT":
            kwargs[name] = opts.get("default", 1.0)
        elif typ == "BOOLEAN":
            kwargs[name] = opts.get("default", False)
        else:
            kwargs[name] = opts.get("default")
    # prompt 必填且不能为空
    if "prompt" in kwargs:
        kwargs["prompt"] = "a cat sitting on a windowsill"
    return kwargs


@pytest.mark.parametrize("node_name", GENERATION_NODES)
def test_node_class_is_wired_to_its_provider(node_name):
    """节点类必须真的能构造出请求体（否则运行到一半才炸）。"""
    node_cls = PLUGIN.NODE_CLASS_MAPPINGS[node_name]
    assert node_cls.IMPL is not None, f"{node_name} 没有设置 IMPL"

    payload = node_cls.build_payload(**_minimal_kwargs(node_cls))
    assert isinstance(payload, dict) and payload, f"{node_name} 构造出了空请求体"
    assert payload.get("model"), f"{node_name} 的请求体里没有 model"


@pytest.mark.parametrize("node_name", GENERATION_NODES)
def test_node_class_declares_its_provider(node_name):
    """节点类的 PROVIDER / KEY_ENV / base_url 必须齐备。"""
    node_cls = PLUGIN.NODE_CLASS_MAPPINGS[node_name]
    assert node_cls.PROVIDER
    assert node_cls.KEY_ENV, f"{node_name} 没有声明 Key 环境变量"
    assert node_cls.DEFAULT_BASE_URL.startswith("https://")


def test_every_node_has_a_display_name():
    for name in PLUGIN.NODE_CLASS_MAPPINGS:
        assert name in PLUGIN.NODE_DISPLAY_NAME_MAPPINGS, f"{name} 缺少显示名"


def test_task_query_nodes_are_registered():
    query_nodes = [k for k in PLUGIN.NODE_CLASS_MAPPINGS if k.endswith("TaskQuery")]
    # 三个异步视频节点 + 一个异步生图节点
    assert len(query_nodes) == 4
    for name in query_nodes:
        cls = PLUGIN.NODE_CLASS_MAPPINGS[name]
        assert cls.IMPL is not None
        assert callable(cls.fetch) and callable(cls.status_of)


def test_image_nodes_output_image_list():
    """生图节点必须输出 IMAGE 列表（一次请求可能出多张）。"""
    for name in GENERATION_NODES:
        cls = PLUGIN.NODE_CLASS_MAPPINGS[name]
        if "Image" not in name and "WanT2I" not in name:
            continue
        assert cls.RETURN_TYPES[0] == "IMAGE", f"{name} 的首个输出类型应是 IMAGE"
        assert cls.OUTPUT_IS_LIST[0] is True, f"{name} 的 IMAGE 输出应是列表"
