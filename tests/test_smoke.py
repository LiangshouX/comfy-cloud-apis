"""协议与逻辑冒烟测试：不触网，只验证请求体构造、状态解析、容错与成本估算。

这些测试无法替代真实 API 验证，但能挡住协议拼写错误与结构性回归。
"""

import pytest

from comfy_cloud_apis.core.credentials import resolve_key
from comfy_cloud_apis.core.task import normalize_status
from comfy_cloud_apis.core.usage import estimate_cost
from comfy_cloud_apis.providers import minimax as mm
from comfy_cloud_apis.providers import qwen_wan as qw
from comfy_cloud_apis.providers import seedance as sd


# --------------------------------------------------------------------------- #
# MiniMax H3
# --------------------------------------------------------------------------- #
def test_minimax_payload_t2v():
    p = mm.MiniMaxProvider.build_payload(
        model="MiniMax-H3", prompt="a cat", resolution="768P", duration=5, ratio="16:9", seed=1
    )
    assert p["model"] == "MiniMax-H3"
    assert p["duration"] == 5
    assert p["ratio"] == "16:9"
    assert p["resolution"] == "768P"
    assert p["content"][0]["type"] == "text"
    assert p["content"][0]["text"].startswith("integrated_multimodal_description:")


def test_minimax_adaptive_ratio_becomes_null():
    assert mm.MiniMaxProvider.build_payload(prompt="x", ratio="adaptive")["ratio"] is None


def test_minimax_structured_prompt_off():
    p = mm.MiniMaxProvider.build_payload(prompt="raw text", use_structured_fields=False)
    assert p["content"][0]["text"] == "raw text"


def test_minimax_frame_and_reference_are_mutually_exclusive():
    with pytest.raises(ValueError):
        mm.MiniMaxProvider.build_payload(
            prompt="x", first_frame_url="http://a", reference_video_url="http://b"
        )


def test_minimax_duration_range():
    with pytest.raises(ValueError):
        mm.MiniMaxProvider.build_payload(prompt="x", duration=30)


def test_minimax_base_url_strips_v1():
    assert mm.MiniMaxProvider.normalize_base_url("https://api.minimaxi.chat/v1") == "https://api.minimaxi.chat"
    assert mm.MiniMaxProvider.normalize_base_url("https://api.minimax.chat/") == "https://api.minimax.chat"


def test_minimax_status_and_url():
    resp = {"task": {"status": "succeeded", "content": {"url": "http://x.mp4"}}}
    assert mm.MiniMaxProvider.status_of(resp) == "succeeded"
    assert mm.MiniMaxProvider.video_url_of(resp) == "http://x.mp4"


# --------------------------------------------------------------------------- #
# Seedance
# --------------------------------------------------------------------------- #
def test_seedance_payload():
    p = sd.SeedanceProvider.build_payload(
        model="doubao-seedance-2-0-fast-260128",
        prompt="a cat",
        duration=5,
        ratio="16:9",
        resolution="720p",
        generate_audio=True,
    )
    assert p["generate_audio"] is True
    assert p["resolution"] == "720p"
    assert p["content"][0]["type"] == "text"


def test_seedance_accepts_both_content_shapes():
    # 官方文档里 content.video_url 出现过对象与裸字符串两种写法
    assert sd.SeedanceProvider.video_url_of({"content": {"video_url": "http://x"}}) == "http://x"
    assert sd.SeedanceProvider.video_url_of({"content": "http://y"}) == "http://y"


def test_seedance_status():
    assert sd.SeedanceProvider.status_of({"status": "succeeded"}) == "succeeded"
    assert sd.SeedanceProvider.status_of({"status": "running"}) == "running"


# --------------------------------------------------------------------------- #
# 通义万相 Wan
# --------------------------------------------------------------------------- #
def test_qwen_payload():
    p = qw.QwenWanProvider.build_payload(
        model="wan2.6-i2v-flash", prompt="a cat", duration=5, size="1280*720"
    )
    assert p["model"] == "wan2.6-i2v-flash"
    assert p["parameters"]["size"] == "1280*720"
    assert p["parameters"]["duration"] == 5
    assert p["input"]["prompt"] == "a cat"


def test_qwen_requires_async_header():
    assert qw.QwenWanProvider.extra_headers().get("X-DashScope-Async") == "enable"


def test_qwen_accepts_both_response_shapes():
    assert qw.QwenWanProvider.status_of({"output": {"task_status": "SUCCEEDED"}}) == "succeeded"
    assert qw.QwenWanProvider.status_of({"status": "SUCCEEDED"}) == "succeeded"
    assert qw.QwenWanProvider.video_url_of({"output": {"video_url": "http://z"}}) == "http://z"
    assert qw.QwenWanProvider.video_url_of({"video_url": "http://w"}) == "http://w"


# --------------------------------------------------------------------------- #
# 通用层
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Success", "succeeded"),
        ("PENDING", "pending"),
        ("running", "running"),
        ("Fail", "failed"),
        ("CANCELED", "cancelled"),
        ("expired", "expired"),
        ("", "unknown"),
    ],
)
def test_status_normalization(raw, expected):
    assert normalize_status(raw) == expected


def test_credential_priority(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "env-key")
    assert resolve_key("", ("MINIMAX_API_KEY",), "minimax", "MiniMax").key == "env-key"
    assert resolve_key("", ("MINIMAX_API_KEY",), "minimax", "MiniMax").source == "env:MINIMAX_API_KEY"
    assert resolve_key("node-key", ("MINIMAX_API_KEY",), "minimax", "MiniMax").source == "node"


def test_cost_estimation():
    c = estimate_cost("MiniMax", "MiniMax-H3", "768P", 5)
    assert c is not None
    assert abs(c["estimated_total"] - 0.4) < 1e-9
    assert c["currency"] == "USD"


def test_cost_estimation_returns_none_when_unknown():
    assert estimate_cost("MiniMax", "不存在的模型", "768P", 5) is None
