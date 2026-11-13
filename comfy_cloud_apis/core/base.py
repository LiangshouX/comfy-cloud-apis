"""节点基类：把「建会话 → 创建任务 → 轮询 → 下载 → 记账」这条链路复用起来。

视频与生图共用同一套骨架，差别只在三处：

    * 结果类型是 VIDEO 还是 IMAGE
    * 同步接口（一次请求直接出结果）还是异步接口（先拿 task_id 再轮询）
    * 计价按秒还是按张

Provider 只需要回答几个问题：
    build_payload()   请求体长什么样
    create()          怎么创建任务
    task_id_of()      task_id 在哪（同步接口返回空串）
    fetch()           怎么查询任务（异步接口才需要）
    status_of()       状态字符串在哪、怎么归一
    results_of()      结果 URL / base64 在哪
    usage_of()        用量信息在哪

其余（凭据、HTTP、轮询、下载、落盘、成本记账）全部由基类统一处理，
保证每一家（以及以后接进来的每一家）行为一致。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Optional

import aiohttp

from .credentials import resolve_key
from .http import dig, download_bytes, download_to
from .media import provider_dir, sniff_image_format
from .outputs import image_output, video_output
from .task import normalize_status, poll_until_done
from .usage import estimate_cost, log_usage


class CloudNodeCommon:
    """所有云端节点的公共部分：元信息、凭据解析、请求头、记录落盘。"""

    # ---- provider 需覆盖的元信息 ----
    PROVIDER: str = "Provider"
    KEY_ENV: tuple = ()
    FILE_KEY: Optional[str] = None
    DEFAULT_BASE_URL: str = ""
    BASE_URL_HINT: str = ""
    CATEGORY: str = "cloud"

    #: True = 异步接口（需要 task_id + 轮询），False = 同步接口
    ASYNC: bool = False
    #: 轮询默认值，各家基类可覆盖（视频官方建议 15 秒，生图 10 秒）
    POLL_INTERVAL_DEFAULT: int = 10
    MAX_WAIT_DEFAULT: int = 600

    #: provider 实现类：负责回答「请求体长什么样 / 结果在哪」这些问题。
    #: 节点类只需 ``IMPL = XxxProvider``，钩子由基类自动转发。
    IMPL: Optional[type] = None

    @classmethod
    def _impl_call(cls, name: str, *args, **kwargs):
        impl = cls.IMPL
        fn = getattr(impl, name, None) if impl is not None else None
        if fn is None:
            raise NotImplementedError(
                f"{cls.__name__} 缺少 {name}()：请检查 IMPL（当前={impl!r}）是否实现了该方法。"
            )
        return fn(*args, **kwargs)

    @classmethod
    def _impl_opt(cls, name: str, *args, **kwargs):
        """可选钩子：provider 没实现就返回 None。"""
        impl = cls.IMPL
        fn = getattr(impl, name, None) if impl is not None else None
        return fn(*args, **kwargs) if fn is not None else None

    # ---- 可选钩子 ----
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
        """所有节点共有的可选输入；异步节点额外带轮询参数。"""
        opt = {
            "save_to_output": (
                "BOOLEAN",
                {"default": True, "tooltip": "是否把结果保存到 ComfyUI/output（否则存 temp）。"},
            ),
        }
        if cls.ASYNC:
            opt = {
                "poll_interval": (
                    "INT",
                    {
                        "default": cls.POLL_INTERVAL_DEFAULT,
                        "min": 3,
                        "max": 120,
                        "tooltip": "轮询间隔（秒）。官方建议 10–15。",
                    },
                ),
                "max_wait": (
                    "INT",
                    {
                        "default": cls.MAX_WAIT_DEFAULT,
                        "min": 60,
                        "max": 3600,
                        "tooltip": "本地最长等待（秒）。超时不代表任务失败——云端可能还在跑，"
                        "请用「任务查询」节点续查，勿重复提交（会重复计费）。",
                    },
                ),
                **opt,
            }
        return opt

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

    def _resolve(self, api_key: str, base_url: str):
        """解析 Key、规整 base_url、拼请求头。"""
        resolved = resolve_key(
            api_key,
            self.KEY_ENV,
            self.FILE_KEY or (self.KEY_ENV[0] if self.KEY_ENV else None),
            self.PROVIDER,
        )
        base = self.normalize_base_url(base_url or self.DEFAULT_BASE_URL)
        if not base:
            raise ValueError("base_url 不能为空。")
        headers = {"Authorization": f"Bearer {resolved.key}", "Content-Type": "application/json"}
        headers.update(self.extra_headers())
        return resolved, base, headers

    def _task_record_dir(self) -> str:
        d = os.path.join(provider_dir(self.PROVIDER, to_output=True), "tasks")
        os.makedirs(d, exist_ok=True)
        return d


class CloudVideoNodeBase(CloudNodeCommon):
    """所有云端视频节点的基类。"""

    ASYNC = True
    POLL_INTERVAL_DEFAULT = 15
    MAX_WAIT_DEFAULT = 900
    CATEGORY = "cloud/video"

    # ---- provider 需实现的方法（由 IMPL 转发） ----
    @classmethod
    def build_payload(cls, **kwargs) -> dict:
        return cls._impl_call("build_payload", **kwargs)

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> str:
        return await cls._impl_call("create", session, base, headers, payload)

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await cls._impl_call("fetch", session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        return cls._impl_call("status_of", resp)

    @classmethod
    def video_url_of(cls, resp: dict) -> str:
        return cls._impl_call("video_url_of", resp)

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return cls._impl_opt("usage_of", resp) or {}

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": cls.common_required(), "optional": cls.common_optional()}

    RETURN_TYPES = ("VIDEO", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video", "file_path", "task_id", "usage_json")
    FUNCTION = "execute"
    CATEGORY = "cloud/video"

    # ---- 执行 ----
    async def _run(self, **kwargs) -> tuple:
        api_key = kwargs.pop("api_key", "")
        base_url = kwargs.pop("base_url", "") or self.DEFAULT_BASE_URL
        poll_interval = int(kwargs.pop("poll_interval", self.POLL_INTERVAL_DEFAULT) or self.POLL_INTERVAL_DEFAULT)
        max_wait = int(kwargs.pop("max_wait", self.MAX_WAIT_DEFAULT) or self.MAX_WAIT_DEFAULT)
        save_to_output = bool(kwargs.pop("save_to_output", True))

        resolved, base, headers = self._resolve(api_key, base_url)
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

    def execute(self, **kwargs):
        dest_path, task_id, usage = _run_async(self._run(**kwargs))
        return (video_output(dest_path), dest_path, task_id, usage)


class CloudImageNodeBase(CloudNodeCommon):
    """所有云端生图节点的基类。

    同时支持两种返回形态：

    * **同步接口**（MiniMax / Seedream / Qwen-Image）：一次请求直接返回图片
    * **异步接口**（通义万相文生图）：先拿 task_id，再轮询任务结果

    provider 只需用 ``task_id_of()`` 返回空串来声明自己是同步接口，
    基类会自动跳过轮询。
    """

    CATEGORY = "cloud/image"

    # ---- provider 需实现的方法（由 IMPL 转发） ----
    @classmethod
    def build_payload(cls, **kwargs) -> dict:
        return cls._impl_call("build_payload", **kwargs)

    @classmethod
    async def create(cls, session, base: str, headers: dict, payload: dict) -> dict:
        """创建生成任务/请求，返回原始响应 dict。"""
        return await cls._impl_call("create", session, base, headers, payload)

    @classmethod
    def task_id_of(cls, resp: dict) -> str:
        """异步接口返回 task_id；同步接口返回空串。"""
        return cls._impl_opt("task_id_of", resp) or ""

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        return await cls._impl_call("fetch", session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        found = cls._impl_opt("status_of", resp)
        return found if found is not None else "succeeded"

    @classmethod
    def results_of(cls, resp: dict) -> list:
        """返回结果列表，每项形如 {"url": "..."} 或 {"base64": "..."}。"""
        return cls._impl_call("results_of", resp)

    @classmethod
    def usage_of(cls, resp: dict) -> dict:
        return cls._impl_opt("usage_of", resp) or {}

    @classmethod
    def trace_id_of(cls, resp: dict) -> str:
        """同步接口没有 task_id，用它当记录文件名。"""
        return str(dig(resp, "id", default="") or dig(resp, "request_id", default="") or "")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": cls.common_required(), "optional": cls.common_optional()}

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "file_paths", "task_id", "usage_json")
    OUTPUT_IS_LIST = (True, True, False, False)
    FUNCTION = "execute"
    CATEGORY = "cloud/image"

    # ---- 执行 ----
    @classmethod
    async def _fetch_result_bytes(cls, session, item: dict) -> bytes:
        """结果项 -> 原始字节。URL 走下载，base64 直接解码。"""
        if item.get("base64"):
            raw = item["base64"]
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[-1]
            return base64.b64decode(raw)
        url = item.get("url") or ""
        if not url:
            raise RuntimeError(f"[{cls.PROVIDER}] 结果项里既没有 url 也没有 base64：{item}")
        if url.startswith("data:"):
            return base64.b64decode(url.split(",", 1)[-1])
        # 下载不带鉴权头：结果 URL 是带签名的公开链接
        return await download_bytes(session, url)

    async def _run(self, **kwargs) -> tuple:
        api_key = kwargs.pop("api_key", "")
        base_url = kwargs.pop("base_url", "") or self.DEFAULT_BASE_URL
        poll_interval = int(kwargs.pop("poll_interval", self.POLL_INTERVAL_DEFAULT) or self.POLL_INTERVAL_DEFAULT)
        max_wait = int(kwargs.pop("max_wait", self.MAX_WAIT_DEFAULT) or self.MAX_WAIT_DEFAULT)
        save_to_output = bool(kwargs.pop("save_to_output", True))

        resolved, base, headers = self._resolve(api_key, base_url)
        payload = self.build_payload(**kwargs)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
            resp = await self.create(session, base, headers, payload)
            task_id = self.task_id_of(resp)
            final = resp

            if task_id:
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
                record["status"] = "succeeded"
                record["usage"] = self.usage_of(final)
                self._write_record(record_path, record)

            results = self.results_of(final)
            if not results:
                raise RuntimeError(f"[{self.PROVIDER}] 未找到生成结果：{final}")

            dest_dir = provider_dir(self.PROVIDER, to_output=save_to_output)
            safe_model = str(kwargs.get("model", "model")).replace("/", "_")
            stamp = time.strftime("%Y%m%d-%H%M%S")
            paths: list[str] = []
            blobs: list[bytes] = []
            for idx, item in enumerate(results):
                data = await self._fetch_result_bytes(session, item)
                ext, _mime = sniff_image_format(data)
                path = os.path.join(dest_dir, f"{safe_model}_{stamp}_{idx:02d}{ext}")
                with open(path, "wb") as fh:
                    fh.write(data)
                paths.append(path)
                blobs.append(data)

        usage = self.usage_of(final)
        cost = estimate_cost(
            self.PROVIDER,
            str(kwargs.get("model", "")),
            str(kwargs.get("size", kwargs.get("resolution", ""))),
            0,
            units=len(results),
        )
        log_usage(
            {
                "provider": self.PROVIDER,
                "model": kwargs.get("model", ""),
                "resolution": kwargs.get("size", kwargs.get("resolution", "")),
                "images": len(results),
                "task_id": task_id,
                "usage": usage,
                "estimated_cost": cost,
                "files": [os.path.basename(p) for p in paths],
            }
        )
        if cost and cost.get("estimated_total") is not None:
            print(
                f"[{self.PROVIDER}] 预估成本 ≈ {cost['estimated_total']} {cost['currency']} "
                f"（{cost['per_image']}/张 × {len(results)}张）"
            )

        try:
            tensors = [image_output(b) for b in blobs]
        except Exception as exc:  # pragma: no cover - 依赖 torch/PIL
            raise RuntimeError(
                f"[{self.PROVIDER}] 图片已保存到 {paths}，但转换成 ComfyUI IMAGE 类型失败：{exc}"
            ) from exc

        return tensors, paths, task_id, json.dumps(usage, ensure_ascii=False)

    def execute(self, **kwargs):
        tensors, paths, task_id, usage = _run_async(self._run(**kwargs))
        return (tensors, paths, task_id, usage)


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

    #: provider 实现类（与生成节点同构，便于共用同一套钩子）
    IMPL: Optional[type] = None

    @classmethod
    async def fetch(cls, session, base: str, headers: dict, task_id: str) -> dict:
        impl = cls.IMPL
        fn = getattr(impl, "fetch", None) if impl is not None else None
        if fn is None:
            raise NotImplementedError(f"{cls.__name__} 缺少 fetch()：请检查 IMPL 是否实现。")
        return await fn(session, base, headers, task_id)

    @classmethod
    def status_of(cls, resp: dict) -> str:
        impl = cls.IMPL
        fn = getattr(impl, "status_of", None) if impl is not None else None
        if fn is None:
            raise NotImplementedError(f"{cls.__name__} 缺少 status_of()：请检查 IMPL 是否实现。")
        return fn(resp)

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
