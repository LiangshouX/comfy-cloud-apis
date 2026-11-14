"""成本估算与用量记账。

设计目标：让用户在 ComfyUI 里就能看到"这一条花了多少钱"，
而不是月底对账单才发现超支。

价格表放在独立的 prices.json 里，**随时可改**，不需要动代码。
核对日期写在每个条目的 checked 字段里——过期的一眼能看出来。
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from .media import ensure_dir, output_root

PRICES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "prices.json")

_cache: Optional[dict] = None


def _load_prices() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(PRICES_FILE, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        except Exception:
            _cache = {}
    return _cache


def estimate_cost(
    provider: str,
    model: str,
    resolution: str = "",
    duration: int = 0,
    units: int = 0,
    usage: Optional[dict] = None,
) -> Optional[dict]:
    """按 provider/model/分辨率 估算成本。价格缺失时返回 None（不瞎猜）。

    支持三种计价：
        * ``per_second`` —— 视频，按输出秒数计
        * ``per_image``  —— 生图，按张数计
        * ``input_token_price`` / ``image_input_token_price`` / ``output_token_price``
          —— 按 token 计（MiniMax H3-Image 是这种，需要传厂商返回的 usage）

    分辨率查不到时回退到该模型的 ``default`` 档。
    """
    prices = _load_prices()
    prov = (prices.get("providers") or {}).get(provider) or {}
    entry = (prov.get("models") or {}).get(model)
    if not entry:
        return None
    resolutions = entry.get("resolutions") or {}
    res = (
        resolutions.get((resolution or "").lower())
        or resolutions.get((resolution or "").upper())
        or resolutions.get("default")
    )
    if not res:
        return None

    currency = res.get("currency", "USD")
    per_second = res.get("per_second")
    per_image = res.get("per_image")
    out_price = res.get("output_token_price")

    if per_second is not None:
        total = round(float(per_second) * float(duration or 0), 4)
        return {
            "currency": currency,
            "per_second": per_second,
            "duration": duration,
            "estimated_total": total,
            "checked": entry.get("checked", ""),
            "source": entry.get("source", ""),
        }
    if per_image is not None:
        count = int(units or 0)
        total = round(float(per_image) * count, 4)
        return {
            "currency": currency,
            "per_image": per_image,
            "images": count,
            "estimated_total": total,
            "checked": entry.get("checked", ""),
            "source": entry.get("source", ""),
        }
    if out_price is not None:
        # 按 token 计：需要厂商返回的 usage 才能算准
        u = usage or {}
        text_in = _dig_num(u, "input_tokens_details", "text_tokens")
        if not text_in:
            text_in = _dig_num(u, "input_tokens")
        img_in = _dig_num(u, "input_tokens_details", "image_tokens")
        out_tokens = _dig_num(u, "output_tokens")
        if not (text_in or img_in or out_tokens):
            return None
        in_price = float(res.get("input_token_price", 0) or 0)
        img_in_price = float(res.get("image_input_token_price", 0) or 0)
        total = round(
            (text_in / 1e6) * in_price
            + (img_in / 1e6) * img_in_price
            + (out_tokens / 1e6) * float(out_price),
            6,
        )
        return {
            "currency": currency,
            "input_tokens": text_in,
            "image_input_tokens": img_in,
            "output_tokens": out_tokens,
            "input_token_price": in_price,
            "image_input_token_price": img_in_price,
            "output_token_price": out_price,
            "estimated_total": total,
            "checked": entry.get("checked", ""),
            "source": entry.get("source", ""),
        }
    return None


def _dig_num(data: dict, *path, default: int = 0) -> int:
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    try:
        return int(cur)
    except (TypeError, ValueError):
        return default


def usage_log_path() -> str:
    d = ensure_dir(os.path.join(output_root(), "comfy_cloud_apis"))
    return os.path.join(d, "usage.jsonl")


def log_usage(record: dict) -> str:
    """把一条用量记录追加到 JSONL。写失败不影响主流程。"""
    record = dict(record)
    record.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
    path = usage_log_path()
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return path
