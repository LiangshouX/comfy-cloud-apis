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
from typing import Any, Optional

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


def estimate_cost(provider: str, model: str, resolution: str, duration: int) -> Optional[dict]:
    """按 provider/model/分辨率 估算成本。价格缺失时返回 None（不瞎猜）。"""
    prices = _load_prices()
    prov = (prices.get("providers") or {}).get(provider) or {}
    entry = (prov.get("models") or {}).get(model)
    if not entry:
        return None
    res = (entry.get("resolutions") or {}).get((resolution or "").lower()) or entry.get("resolutions", {}).get(
        (resolution or "").upper()
    )
    if not res:
        return None
    per_second = res.get("per_second")
    if per_second is None:
        return None
    currency = res.get("currency", "USD")
    total = round(float(per_second) * float(duration), 4)
    return {
        "currency": currency,
        "per_second": per_second,
        "duration": duration,
        "estimated_total": total,
        "checked": entry.get("checked", ""),
        "source": entry.get("source", ""),
    }


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
