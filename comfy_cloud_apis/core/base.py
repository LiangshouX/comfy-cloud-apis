"""节点基类：把「建会话 → 创建任务 → 轮询 → 下载 → 记账」这条链路复用起来。

Provider 只需要回答 6 个问题：
    build_payload()   请求体长什么样
    create()          怎么创建任务、task_id 在哪
    fetch()           怎么查询任务
    status_of()       状态字符串在哪、怎么归一
    video_url_of()    成片 URL 在哪
    usage_of()        用量信息在哪

其余（凭据、HTTP、轮询、下载、落盘、成本记账）全部由基类统一处理，
保证三家（以及以后接进来的每一家）行为一致。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

import aiohttp

from .credentials import resolve_key
from .http import download_to, request_json
from .media import provider_dir
from .outputs import video_output
from .task import normalize_status, poll_until_done
from .usage import estimate_cost, log_usage


class CloudVideoNodeBase:
    """所有云端视频节点的基类。"""

    # ---- provider 需覆盖的元信息 ----
    PROVIDER: str = "Provider"
    KEY_ENV: tuple = ()
    FILE_KEY: Optional[str] = None
    DEFAULT_BASE_URL: str = ""
    BASE_URL_HINT: str = ""
    CATEGORY: str = "cloud/video"

    # ---- provider 需实现的方法 ----
    @classmethod
    def build_payload(cls, **kwargs) -> dict:
        raise NotImplementedError

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> str:
        raise NotImplementedError

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        raise NotImplementedError

    @classmethod
    def status_of(cls, resp: dict) -> str:
        raise NotImplementedError

    @classmethod
    def video_url_of(cls, resp: dict) -> str:
        raise NotImplementedError

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return {}

    # ---- 可选的钩子 ----
    @classmethod
    def normalize_base_url(cls, raw: str) -> str:
        return (raw or "").strip().rstrip("/")

    @classmethod
    def extra_headers(cls) -> dict:
        return {}

    @classmethod
    def common_required(cls) -> dict:
        return {
            "api_key": (
                "STRING",
                {
                    "default": "",
                    "multiline": False,
                    "tooltip": f"{cls.PROVIDER} API Key（Bearer）。留空则读取环境变量 "
                               f"{' / '.join(cls.KEY_ENV)} —— 推荐后者，导出的工作流不含密钥。",
                },
            ),
            "base_url": (
                "STRING",
                {
                    "default": cls.DEFAULT_BASE_URL,
                    "tooltip": cls.BASE_URL_HINT or f"{cls.PROVIDER} API 根地址。",
                },
            ),
        }

    @classmethod
    def common_optional(cls) -> dict:
        return {
            "poll_interval": (
                "INT",
                {"default": 15, "min": 5, "max": 120, "tooltip": "轮询间隔（秒）。官方建议 10–15。"},
            ),
            "max_wait": (
                "INT",
                {
                    "default": 900,
                    "min": 60,
                    "max": 3600,
                    "tooltip": "本地最长等待（秒）。超时不代表任务失败——云端可能还在跑，"
                    "请用「任务查询」节点续查，勿重复提交（会重复计费）。",
                },
            ),
            "save_to_output": (
                "BOOLEAN",
                {"default": True, "tooltip": "是否把成片保存到 ComfyUI/output（否则存 temp）。"},
            ),
        }

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": cls.common_required(), "optional": cls.common_optional()}

    RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video", "file_path", "task_id", "usage_json")
    FUNCTION = "execute"
    CATEGORY = "cloud/video"

    # ---- 执行 ----
    def _task_record_dir(self) -> str:
        d = os.path.join(provider_dir(self.PROVIDER, to_output=True), "tasks")
        os.makedirs(d, exist_ok=True)
        return d

    async def _run(self, **kwargs) -> tuple:
        api_key = kwargs.pop("api_key", "")
        base_url = kwargs.pop("base_url", "") or self.DEFAULT_BASE_URL
        poll_interval = int(kwargs.pop("poll_interval", 15) or 15)
        max_wait = int(kwargs.pop("max_wait", 900) or 900)
        save_to_output = bool(kwargs.pop("save_to_output", True))

        resolved = resolve_key(
            api_key, self.KEY_ENV, self.FILE_KEY or (self.KEY_ENV[0] if self.KEY_ENV else None), self.PROVIDER
        )
        base = self.normalize_base_url(base_url)
        if not base:
            raise ValueError("base_url 不能为空。")

        headers = {"Authorization": f"Bearer {resolved.key}", "Content-Type": "application/json"}
        headers.update(self.extra_headers())

        payload = self.build_payload(**kwargs)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
            task_id = await self.create(session, base, headers, payload)
            if not task_id:
                raise RuntimeError(f"[{self.PROVIDER}] 未返回 task_id。")

            record = {
                "provider": self.PROVIDER,
                "task_id": task_id,
                "payload_summary": self._payload_summary(payload),
                "key_source": resolved.source,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "created",
            }
            record_path = os.path.join(self._task_record_dir(), f"{task_id}.json")
            self._write_record(record_path, record)
            print(f"[{self.PROVIDER}] task_id={task_id}（{resolved.source}），记录于 {record_path}")

            async def _fetch():
                return await self.fetch(session, base, headers, task_id)

            try:
                final = await poll_until_done(
                    _fetch,
                    self.status_of,
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                    on_tick=lambda st, _p: print(f"[{self.PROVIDER}] task {task_id} -> {st}"),
                )
            except TimeoutError as exc:
                record["note"] = "本地等待超时；云端任务可能仍在执行，请勿重复提交。"
                self._write_record(record_path, record)
                raise RuntimeError(
                    f"[{self.PROVIDER}] {exc}\ntask_id={task_id}\n"
                    f"用「任务查询」节点查这个 task_id，或查看 {record_path}"
                ) from exc

            video_url = self.video_url_of(final)
            if not video_url:
                raise RuntimeError(f"[{self.PROVIDER}] 任务成功但未找到成片 URL：{final}")

            record["status"] = "succeeded"
            record["video_url"] = video_url
            record["usage"] = self.usage_of(final)
            self._write_record(record_path, record)

            dest_dir = provider_dir(self.PROVIDER, to_output=save_to_output)
            safe_model = str(kwargs.get("model", "model")).replace("/", "_")
            dest_path = os.path.join(
                dest_dir,
                f"{safe_model}_{time.strftime('%Y%m%d-%H%M%S')}_{task_id}.mp4",
            )
            # 下载不带鉴权头：成片 URL 是带签名的公开链接
            await download_to(session, video_url, dest_path)

        usage = self.usage_of(final)
        cost = estimate_cost(
            self.PROVIDER,
            str(kwargs.get("model", "")),
            str(kwargs.get("resolution", kwargs.get("size", ""))),
            int(kwargs.get("duration", 0) or 0),
        )
        log_usage(
            {
                "provider": self.PROVIDER,
                "model": kwargs.get("model", ""),
                "resolution": kwargs.get("resolution", kwargs.get("size", "")),
                "duration": kwargs.get("duration"),
                "task_id": task_id,
                "usage": usage,
                "estimated_cost": cost,
                "file": os.path.basename(dest_path),
            }
        )
        if cost and cost.get("estimated_total") is not None:
            print(
                f"[{self.PROVIDER}] 预估成本 ≈ {cost['estimated_total']} {cost['currency']} "
                f"（{cost['per_second']}/秒 × {cost['duration']}秒）"
            )

        return dest_path, task_id, json.dumps(usage, ensure_ascii=False)

    @classmethod
    def _payload_summary(cls, payload: dict) -> dict:
        """任务记录里只留摘要，不留完整 prompt（避免敏感内容落盘）。"""
        out = {}
        for k, v in (payload or {}).items():
            if k == "content" and isinstance(v, list):
                out["content_roles"] = [c.get("role", c.get("type")) for c in v]
            elif isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            else:
                out[k] = str(v)[:120]
        return out

    @staticmethod
    def _write_record(path: str, record: dict) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def execute(self, **kwargs):
        dest_path, task_id, usage = _run_async(self._run(**kwargs))
        return (video_output(dest_path), dest_path, task_id, usage)


class CloudTaskQueryNode:
    """通用任务查询节点：拿 task_id 查状态，避免重复提交导致重复计费。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": (
                    "STRING",
                    {"default": "", "tooltip": "留空则读取环境变量。"},
                ),
                "base_url": ("STRING", {"default": ""}),
                "task_id": ("STRING", {"default": "", "tooltip": "要查询的 task_id。"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("status", "result_json")
    FUNCTION = "execute"
    CATEGORY = "cloud/video"

    PROVIDER = "Provider"
    KEY_ENV: tuple = ()
    FILE_KEY: Optional[str] = None
    DEFAULT_BASE_URL: str = ""
    BASE_URL_HINT: str = ""

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        raise NotImplementedError

    @classmethod
    def status_of(cls, resp: dict) -> str:
        raise NotImplementedError

    @classmethod
    def normalize_base_url(cls, raw: str) -> str:
        return (raw or "").strip().rstrip("/")

    @classmethod
    def extra_headers(cls) -> dict:
        return {}

    def execute(self, api_key, base_url, task_id):
        task_id = (task_id or "").strip()
        if not task_id:
            raise ValueError("task_id 不能为空。")
        resolved = resolve_key(
            api_key, self.KEY_ENV, self.FILE_KEY or (self.KEY_ENV[0] if self.KEY_ENV else None), self.PROVIDER
        )
        base = self.normalize_base_url(base_url or self.DEFAULT_BASE_URL)
        headers = {"Authorization": f"Bearer {resolved.key}", "Content-Type": "application/json"}
        headers.update(self.extra_headers())

        async def _q():
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
                return await self.fetch(session, base, headers, task_id)

        resp = _run_async(_q())
        return (normalize_status(self.status_of(resp)), json.dumps(resp, ensure_ascii=False))


def _run_async(coro):
    """在同步的 ComfyUI 节点里安全地跑协程。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
