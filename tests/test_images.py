"""生图节点的协议与逻辑测试：不触网，只验证请求体构造、响应解析、容错与计价。

这些测试无法替代真实 API 验证，但能挡住协议拼写错误与结构性回归。
"""

import pytest

from comfy_cloud_apis.core.media import sniff_image_format
from comfy_cloud_apis.core.usage import estimate_cost
from comfy_cloud_apis.providers import minimax_image as mm_img
from comfy_cloud_apis.providers import qwen_image as qwen_img
from comfy_cloud_apis.providers import seedream as sd_img
from comfy_cloud_apis.providers import wan_image as wan_img


# --------------------------------------------------------------------------- #
# MiniMax image-01
# --------------------------------------------------------------------------- #
def test_minimax_image_payload_t2i():
    p = mm_img.MiniMaxImageProvider.build_payload(
        model="image-01", prompt="a cat", aspect_ratio="16:9", n=2, seed=7
    )
    assert p["model"] == "image-01"
    assert p["prompt"] == "a cat"
    assert p["aspect_ratio"] == "16:9"
    assert p["n"] == 2
    assert p["response_format"] == "url"


def test_minimax_image_custom_size_replaces_aspect_ratio():
    # 官方规则：aspect_ratio 与 width/height 同时给时 aspect_ratio 优先，
    # 所以自定义尺寸时不应再下发 aspect_ratio。
    p = mm_img.MiniMaxImageProvider.build_payload(prompt="x", width=1280, height=720)
    assert p["width"] == 1280 and p["height"] == 720
    assert "aspect_ratio" not in p


def test_minimax_image_rejects_bad_size():
    # 官方约束：512–2048 且必须是 8 的倍数
    with pytest.raises(ValueError):
        mm_img.MiniMaxImageProvider.build_payload(prompt="x", width=1001, height=720)
    with pytest.raises(ValueError):
        mm_img.MiniMaxImageProvider.build_payload(prompt="x", width=256, height=720)


def test_minimax_image_n_range():
    with pytest.raises(ValueError):
        mm_img.MiniMaxImageProvider.build_payload(prompt="x", n=10)


def test_minimax_image_prompt_length_limit():
    with pytest.raises(ValueError):
        mm_img.MiniMaxImageProvider.build_payload(prompt="x" * 1501)


def test_minimax_image_subject_reference():
    p = mm_img.MiniMaxImageProvider.build_payload(prompt="x", reference_image_url="https://a/b.jpg")
    ref = p["subject_reference"][0]
    assert ref["type"] == "character"
    assert ref["image_file"] == "https://a/b.jpg"


def test_minimax_image_style_only_for_live():
    with pytest.raises(ValueError):
        mm_img.MiniMaxImageProvider.build_payload(prompt="x", model="image-01", style_type="漫画")
    p = mm_img.MiniMaxImageProvider.build_payload(prompt="x", model="image-01-live", style_type="漫画")
    assert p["style"]["style_type"] == "漫画"


def test_minimax_image_results_of_both_forms():
    assert mm_img.MiniMaxImageProvider.results_of(
        {"data": {"image_urls": ["https://x/1.png", "https://x/2.png"]}}
    ) == [{"url": "https://x/1.png"}, {"url": "https://x/2.png"}]
    assert mm_img.MiniMaxImageProvider.results_of(
        {"data": {"image_base64": ["QUJD"]}}
    ) == [{"base64": "QUJD"}]
    assert mm_img.MiniMaxImageProvider.results_of({"data": {}}) == []


def test_minimax_image_base_url_strips_v1():
    # 视频节点会剥掉 /v1，生图节点的路径里再补回去，避免 /v1/v1
    assert mm_img.MiniMaxImageProvider.normalize_base_url("https://api.minimax.chat/v1") == (
        "https://api.minimax.chat"
    )


# --------------------------------------------------------------------------- #
# Seedream（即梦）
# --------------------------------------------------------------------------- #
def test_seedream_payload_t2i():
    p = sd_img.SeedreamProvider.build_payload(
        model="doubao-seedream-4-0-250828", prompt="a cat", size="2K"
    )
    assert p["model"] == "doubao-seedream-4-0-250828"
    assert p["prompt"] == "a cat"
    assert p["size"] == "2K"
    assert p["response_format"] == "url"


def test_seedream_sequential_images():
    p = sd_img.SeedreamProvider.build_payload(
        model="doubao-seedream-4-0-250828", prompt="x", max_images=4
    )
    assert p["sequential_image_generation"] == "auto"
    assert p["sequential_image_generation_options"]["max_images"] == 4


def test_seedream_sequential_not_supported_on_3x():
    with pytest.raises(ValueError):
        sd_img.SeedreamProvider.build_payload(
            model="doubao-seedream-3-0-t2i-250415", prompt="x", max_images=4
        )


def test_seedream_seed_only_for_3x():
    with pytest.raises(ValueError):
        sd_img.SeedreamProvider.build_payload(
            model="doubao-seedream-4-0-250828", prompt="x", seed=123
        )
    p = sd_img.SeedreamProvider.build_payload(
        model="doubao-seedream-3-0-t2i-250415", prompt="x", seed=123
    )
    assert p["seed"] == 123


def test_seedream_reference_image_as_list():
    p = sd_img.SeedreamProvider.build_payload(
        model="doubao-seedream-4-0-250828",
        prompt="x",
        reference_image_url="https://a/1.png",
    )
    assert p["image"] == "https://a/1.png"


def test_seedream_output_format_only_for_5x():
    with pytest.raises(ValueError):
        sd_img.SeedreamProvider.build_payload(
            model="doubao-seedream-4-0-250828", prompt="x", output_format="png"
        )
    p = sd_img.SeedreamProvider.build_payload(
        model="doubao-seedream-5-0-260128", prompt="x", output_format="png"
    )
    assert p["output_format"] == "png"


def test_seedream_web_search_only_for_5x():
    with pytest.raises(ValueError):
        sd_img.SeedreamProvider.build_payload(
            model="doubao-seedream-4-0-250828", prompt="x", web_search=True
        )


def test_seedream_results_of():
    resp = {"data": [{"url": "https://x/1.png", "size": "2048x2048"}]}
    assert sd_img.SeedreamProvider.results_of(resp) == [{"url": "https://x/1.png"}]
    resp_b64 = {"data": [{"b64_json": "QUJD"}]}
    assert sd_img.SeedreamProvider.results_of(resp_b64) == [{"base64": "QUJD"}]


# --------------------------------------------------------------------------- #
# 千问 Qwen-Image
# --------------------------------------------------------------------------- #
def test_qwen_image_payload_structure():
    p = qwen_img.QwenImageProvider.build_payload(
        model="qwen-image-2.0-pro", prompt="a cat", size="2048*2048", n=2
    )
    assert p["model"] == "qwen-image-2.0-pro"
    msg = p["input"]["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"][0]["text"] == "a cat"
    assert p["parameters"]["size"] == "2048*2048"
    assert p["parameters"]["n"] == 2
    assert p["parameters"]["prompt_extend"] is True


def test_qwen_image_negative_prompt_truncated():
    p = qwen_img.QwenImageProvider.build_payload(prompt="x", negative_prompt="n" * 900)
    assert len(p["parameters"]["negative_prompt"]) == 500


def test_qwen_image_n_fixed_for_plus_and_max():
    with pytest.raises(ValueError):
        qwen_img.QwenImageProvider.build_payload(model="qwen-image-plus", prompt="x", n=3)


def test_qwen_image_results_of():
    resp = {
        "output": {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": [{"image": "https://x/1.png"}]},
                }
            ]
        }
    }
    assert qwen_img.QwenImageProvider.results_of(resp) == [{"url": "https://x/1.png"}]
    assert qwen_img.QwenImageProvider.results_of({"output": {}}) == []


def test_qwen_image_reference_image_content():
    p = qwen_img.QwenImageProvider.build_payload(
        prompt="x", reference_image_url="https://a/1.png"
    )
    content = p["input"]["messages"][0]["content"]
    assert content[0]["text"] == "x"
    assert content[1]["image"] == "https://a/1.png"


# --------------------------------------------------------------------------- #
# 通义万相 文生图（异步）
# --------------------------------------------------------------------------- #
def test_wan_image_requires_async_header():
    assert wan_img.WanImageProvider.extra_headers().get("X-DashScope-Async") == "enable"


def test_wan_image_payload():
    p = wan_img.WanImageProvider.build_payload(
        model="wan2.6-t2i", prompt="a cat", size="1024*1024", n=2
    )
    assert p["model"] == "wan2.6-t2i"
    assert p["input"]["prompt"] == "a cat"
    assert p["parameters"]["size"] == "1024*1024"
    assert p["parameters"]["n"] == 2


def test_wan_image_n_range():
    with pytest.raises(ValueError):
        wan_img.WanImageProvider.build_payload(prompt="x", n=5)


def test_wan_image_task_id_and_status():
    resp = {"output": {"task_id": "abc-123", "task_status": "PENDING"}}
    assert wan_img.WanImageProvider.task_id_of(resp) == "abc-123"
    assert wan_img.WanImageProvider.status_of(resp) == "pending"
    done = {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://x/1.png"}]}}
    assert wan_img.WanImageProvider.status_of(done) == "succeeded"
    assert wan_img.WanImageProvider.results_of(done) == [{"url": "https://x/1.png"}]


# --------------------------------------------------------------------------- #
# 通用层
# --------------------------------------------------------------------------- #
def test_image_cost_per_image():
    c = estimate_cost("MiniMax", "image-01", "", 0, units=3)
    assert c is not None
    assert c["per_image"] == 0.025
    assert c["images"] == 3
    assert abs(c["estimated_total"] - 0.075) < 1e-9
    assert c["currency"] == "CNY"


def test_image_cost_falls_back_to_default_resolution():
    # 生图节点的分辨率参数各家写法不同（1:1 / 2K / 2048*2048），
    # 查不到时必须回退到 default 档，否则算不出成本。
    c = estimate_cost("Seedream", "doubao-seedream-4-0-250828", "2048x2048", 0, units=1)
    assert c is not None
    assert abs(c["estimated_total"] - 0.2) < 1e-9


def test_video_cost_still_works():
    c = estimate_cost("MiniMax", "MiniMax-H3", "768P", 5)
    assert c is not None
    assert c["per_second"] == 0.08
    assert abs(c["estimated_total"] - 0.4) < 1e-9


def test_sniff_image_format():
    assert sniff_image_format(b"\x89PNG\r\n\x1a\n" + b"0" * 32) == (".png", "image/png")
    assert sniff_image_format(b"\xff\xd8\xff\xe0" + b"0" * 32) == (".jpg", "image/jpeg")
    assert sniff_image_format(b"RIFF" + b"0000" + b"WEBP") == (".webp", "image/webp")
    assert sniff_image_format(b"") == (".png", "image/png")


# --------------------------------------------------------------------------- #
# 端到端流程（用假 session 跑完整条 落盘 -> tensor 链路，不触网）
# --------------------------------------------------------------------------- #
def _make_png_b64():
    import base64 as _b64
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buf, format="PNG")
    return _b64.b64encode(buf.getvalue()).decode()


class _FakeResponse:
    """最小可用的 aiohttp 响应替身。"""

    def __init__(self, payload):
        self._payload = payload
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self):
        import json as _json

        return _json.dumps(self._payload)

    async def read(self):
        return b""


def _fake_session_class(payload):
    """构造一个总是返回同一份 payload 的 ClientSession 替身。"""

    class _S:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def request(self, method, url, headers=None, json=None, timeout=None):
            return _FakeResponse(payload)

        def get(self, url, headers=None, timeout=None):
            return _FakeResponse(payload)

    return _S


def _run_seedream_node(monkeypatch):
    from comfy_cloud_apis.core import base as base_mod

    png_b64 = _make_png_b64()
    payload = {
        "model": "doubao-seedream-4-0-250828",
        "created": 1764041608,
        "data": [{"b64_json": png_b64, "size": "2048x2048"}],
        "usage": {"generated_images": 1, "output_tokens": 1, "total_tokens": 1},
    }
    monkeypatch.setattr(base_mod.aiohttp, "ClientSession", _fake_session_class(payload))

    node = sd_img.SeedreamImageNode()
    return node.execute(
        api_key="fake-key-for-test",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-seedream-4-0-250828",
        prompt="a cat",
        size="2K",
        response_format="b64_json",
    )


def test_image_node_flow_writes_files(monkeypatch):
    """同步生图节点的完整编排：响应 -> 解码 -> 落盘 -> 记账。

    image_output 被替换成桩，因此**没有 torch 也能跑**，
    用来覆盖最容易出结构性回归的那段流程。
    """
    import os as _os

    from comfy_cloud_apis.core import base as base_mod

    monkeypatch.setattr(base_mod, "image_output", lambda b: ("TENSOR", len(b)))

    images, paths, task_id, usage_json = _run_seedream_node(monkeypatch)

    assert len(images) == 1
    assert isinstance(images[0], tuple) and images[0][0] == "TENSOR"
    assert len(paths) == 1
    assert _os.path.isfile(paths[0])
    assert paths[0].endswith(".png")
    assert task_id == ""  # 同步接口没有 task_id
    assert "generated_images" in usage_json


def test_image_node_flow_returns_real_tensor(monkeypatch):
    """同上，但要求真的转成 ComfyUI IMAGE tensor（需要 torch）。"""
    import os as _os

    pytest.importorskip("torch")

    images, paths, _task_id, _usage = _run_seedream_node(monkeypatch)

    assert len(images) == 1
    assert _os.path.isfile(paths[0])
    # IMAGE tensor 形状应为 [1, H, W, C]
    assert tuple(images[0].shape) == (1, 2, 2, 3)


def test_bytes_to_tensor_shape():
    """图片字节 -> IMAGE tensor 的形状与像素归一化。"""
    pytest.importorskip("torch")

    import base64 as _b64

    from comfy_cloud_apis.core.media import bytes_to_tensor

    data = _b64.b64decode(_make_png_b64())
    t = bytes_to_tensor(data, mode="RGB")
    assert tuple(t.shape) == (1, 2, 2, 3)
    assert abs(float(t[0, 0, 0, 0]) - 10 / 255.0) < 1e-4
