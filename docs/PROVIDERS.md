# 各厂商 API 契约对照

> 核对日期：**2026-11-13**。厂商 API 会变，落地前请以官方文档为准。
> 本文只记录**本项目实际实现**的契约，以及实现时踩到的差异点。

---

## 1. MiniMax H3

**官方文档**：<https://platform.minimaxi.com/document/Video%20Generation>

### 端点

| 动作 | 方法 | 路径 |
|---|---|---|
| 创建任务 | POST | `{base}/v2/video_generation` |
| 查询任务 | GET | `{base}/v2/query/video_generation/{task_id}` |
| Context-IR（提示词结构化，未实现） | POST | `{base}/v2/h3_context_ir` |
| 768P → 2K 再生成（未实现） | POST | `{base}/v2/video_regeneration` |

**base_url**：国内 `https://api.minimax.chat` ／ 国际 `https://api.minimaxi.chat` ／ 备用 `https://api.minimax.io`

### 请求体

```json
{
  "model": "MiniMax-H3",
  "content": [
    {"type": "text", "text": "integrated_multimodal_description: ..."},
    {"type": "image_url", "image_url": {"url": "..."}, "role": "first_frame"},
    {"type": "video_url", "video_url": {"url": "..."}, "role": "reference_video"},
    {"type": "audio_url", "audio_url": {"url": "..."}, "role": "reference_audio"}
  ],
  "resolution": "768P",
  "duration": 5,
  "ratio": "16:9",
  "seed": 42,
  "aigc_watermark": false
}
```

- `role` 取值：`first_frame` / `last_frame` / `reference_image` / `reference_video` / `reference_audio`
- **首尾帧角色与参考角色互斥**，官方不允许同一次请求混用
- 参考音频必须与至少一张参考图或一段参考视频同时提供
- `ratio` 传 `null` 等价于 `adaptive`
- `duration` 4–15 秒整数；`resolution` 为 `768P` / `2K`

### 响应

```json
// 创建
{"task_id": "424010985738629"}

// 查询
{"task": {"id": "...", "status": "succeeded",
          "content": {"url": "https://.../out.mp4"},
          "usage": {"total_seconds": 5, "input_seconds": 0, "output_seconds": 5}}}
```

状态词：`queued` / `running` / `succeeded` / `failed` / `cancelled` / `expired`

### 计费（2026-11-09 核对）

| 模型 | 768P | 2K | 480P |
|---|---|---|---|
| MiniMax-H3 | $0.08/s | $0.13/s | — |
| MiniMax-H3-Max | $0.08/s | — | $0.05/s |
| MiniMax-H3-Highspeed | $0.06/s | — | $0.04/s |
| MiniMax-H3-Lite | $0.04/s | — | $0.025/s |

附加：768P→2K 再生成 $0.05/s；前 5 张参考图免费，第 6 张起 $0.04/张；参考视频按输入时长计费；音频参考免费。
国内开放平台口径：768P ¥0.50/s、2K ¥0.80/s。

### 限制

- 请求体上限 64MB（官方文档）→ 大图建议走 URL
- 文本与音视频参考上限：9 图 / 3 视频 / 3 音频，合计 ≤12 个文件
- 参考视频 2–15 秒，参考音频 2–15 秒
- 免费额度下 H3 V2 最多 **2 个并发任务**，付费额度 15 个

### ⚠️ 版本陷阱

**V1 是老的 Hailuo，V2 才是 H3。** 社区里大量示例代码混用了两套协议：

| | V1（Hailuo） | V2（H3） |
|---|---|---|
| 创建 | `/v1/video_generation` | `/v2/video_generation` |
| 查询 | `/v1/query/video_generation?task_id=` | `/v2/query/video_generation/{task_id}` |
| 模型 | `T2V-01` / `I2V-01` | `MiniMax-H3` |
| 提示词 | 顶层 `prompt` | `content[]` 数组 |
| 取成片 | `file_id` → `/v1/files/retrieve` | `task.content.url` |

混用会得到"看起来合理但跑不通"的代码。本项目只实现 V2。

---

## 2. Seedance（豆包 / 火山方舟）

**官方文档**：<https://docs.volcengine.com/docs/82379/2298881>

### 端点

| 动作 | 方法 | 路径 |
|---|---|---|
| 创建任务 | POST | `{base}/contents/generations/tasks` |
| 查询任务 | GET | `{base}/contents/generations/tasks/{id}` |
| 查询列表 | GET | `{base}/contents/generations/tasks?page_num=&page_size=` |
| 取消/删除 | DELETE | `{base}/contents/generations/tasks/{id}` |

**base_url**：`https://ark.cn-beijing.volces.com/api/v3`
**鉴权**：`Authorization: Bearer $ARK_API_KEY`

### 请求体

```json
{
  "model": "doubao-seedance-2-0-fast-260128",
  "content": [
    {"type": "text", "text": "..."},
    {"type": "image_url", "image_url": {"url": "https://..."}, "role": "first_frame"}
  ],
  "generate_audio": true,
  "ratio": "adaptive",
  "duration": 5,
  "watermark": false,
  "resolution": "720p",
  "seed": 42,
  "camera_fixed": false,
  "service_tier": "default"
}
```

- `service_tier: "flex"` = 离线推理，**通常半价**
- `role` 取值：`first_frame` / `last_frame` / `reference_image` / `reference_video` / `reference_audio`
- `ratio`：`21:9` / `16:9` / `4:3` / `1:1` / `3:4` / `9:16` / `adaptive`
- `resolution`：`480p` / `720p` / `1080p` / `4k`（4k 仅 2.5 支持）

### 模型 ID 与能力

| 模型 ID | 文生 | 首帧 | 首尾帧 | 视频参考 | 音频参考 | 有声 | 延长 | 编辑 | 分辨率 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `doubao-seedance-2-5-260628` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 4k |
| `doubao-seedance-2-0-260128` | ✓ | ✓ | ✓ | ✓ | ✓(需配图/视频) | ✓ | ✓ | ✓ | 1080p |
| `doubao-seedance-2-0-fast-260128` | ✓ | ✓ | ✓ | ✓ | ✓(需配图/视频) | ✓ | ✓ | ✓ | 720p |
| `doubao-seedance-2-0-mini-260615` | ✓ | ✓ | ✓ | ✓ | ✓(需配图/视频) | ✓ | ✓ | ✓ | 720p |
| `doubao-seedance-1-0-pro-250528` | ✓ | ✓ | ✓ | — | — | — | — | — | 1080p |
| `doubao-seedance-1-0-pro-fast-251015` | ✓ | ✓ | — | — | — | — | — | — | 1080p |

**模型 ID 必须是你在方舟控制台创建过推理接入点的**，否则报"模型不存在"。

### 响应

```json
{"id": "cgt-2025xxxx", "model": "...", "status": "succeeded",
 "content": {"video_url": "https://.../out.mp4"},
 "usage": {"completion_tokens": 246840, "total_tokens": 246840},
 "created_at": 1765510475, "updated_at": 1765510559,
 "seed": 58944, "resolution": "1080p", "ratio": "16:9", "duration": 5, "framespersecond": 24}
```

状态词：`queued` / `running` / `succeeded` / `failed`

> ⚠️ **实现细节**：官方文档里 `content.video_url` 出现过两种形态——对象
> `{"content": {"video_url": "..."}}` 与裸字符串。本项目用容错取值，两种都支持。

### 图片输入

官方示例**一律用公网 URL**。data URI 未被明确承诺，本项目默认优先用 URL；
只有在没给 URL 时才退回内联 base64，并打印警告。

---

## 3. 通义万相 Wan（阿里云百炼）

**官方文档**：<https://help.aliyun.com/zh/model-studio/video-generation-api-reference>

### 端点

| 动作 | 方法 | 路径 |
|---|---|---|
| 创建任务 | POST | `{base}/api/v1/services/aigc/video-generation/video-synthesis` |
| 查询任务 | GET | `{base}/api/v1/tasks/{task_id}` |

**base_url**：

| 地域 | 旧域名 | 业务空间专属域名（推荐） |
|---|---|---|
| 北京 | `https://dashscope.aliyuncs.com` | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com` |
| 新加坡 | `https://dashscope-intl.aliyuncs.com` | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com` |
| 美国弗吉尼亚 | — | `https://{WorkspaceId}.us-east-1.maas.aliyuncs.com` |
| 德国法兰克福 | — | `https://{WorkspaceId}.eu-central-1.maas.aliyuncs.com` |

> **模型、域名、API Key 必须属于同一地域**，跨地域调用会失败。

### ⚠️ 必须的请求头

```http
X-DashScope-Async: enable
```

缺这个头会直接报：`current user api does not support synchronous calls`

### 请求体

```json
{
  "model": "wan2.6-i2v-flash",
  "input": {
    "prompt": "...",
    "img_url": "data:image/png;base64,...",
    "audio_url": "https://...",
    "negative_prompt": "...",
    "reference_urls": ["https://..."]
  },
  "parameters": {
    "size": "1280*720",
    "duration": 5,
    "resolution": "720P",
    "prompt_extend": true,
    "audio": true,
    "shot_type": "single",
    "watermark": false,
    "seed": 42
  }
}
```

- `size` 必须是**具体数值** `宽*高`，不能写 `16:9` 或 `720P`
- `shot_type`：`single`（默认，单镜头）/ `multi`（多镜头叙事）
- `duration`：r2v 系列 2–10 秒；i2v flash 可到 10–15 秒
- 万相**支持反向提示词**（H3 不支持，因为是 CFG-distilled）

### ✅ 图片可以直接内联 base64

官方 Java/Python 示例明确支持三种方式：公网 URL、`file://` 本地路径、
`data:{MIME_type};base64,{base64_data}`。

**这是三家里唯一明确承诺支持内联的**，所以本地图片在百炼这里不需要先传图床。

### 响应

```json
{"request_id": "...", "output": {"task_id": "...", "task_status": "PENDING"}}
```

```json
{"request_id": "...",
 "output": {"task_id": "...", "task_status": "SUCCEEDED",
            "video_url": "https://dashscope-result-...oss.../xxx.mp4?Expires=...",
            "submit_time": "...", "end_time": "..."},
 "usage": {"video_count": 1, "duration": 10.0, "output_video_duration": 10, "SR": 720}}
```

状态词：`PENDING` / `RUNNING` / `SUCCEEDED` / `FAILED` / `CANCELED` / `UNKNOWN`

> 较新版本响应是 `{"output": {...}}` 包裹，较旧版本是顶层 `{"status": ..., "video_url": ...}`。
> 本项目两种都兼容。

### ⏳ 24 小时有效期

`task_id` 与 `video_url` **只保留 24 小时**，过期后无法查询或下载。
本项目在任务成功后立即下载到本地。

### 模型

`wan2.6-t2v` / `wan2.6-i2v` / `wan2.6-i2v-flash` / `wan2.6-r2v` / `wan2.6-r2v-flash`

---

## 4. 共同的错误处理

HTTP 层把状态码翻译成可执行动作，provider 可以覆盖：

| 码 | 通用含义 |
|---|---|
| 400 | 请求参数被拒（检查模型名、必填参数、取值范围） |
| 401 | 鉴权失败（Key 错误/过期/与 base_url 不同地域） |
| 402 | 余额不足 |
| 403 | 无权调用该模型 |
| 404 | 路径或模型不存在 |
| 413 | 请求体过大（改用 URL 而不是内联 base64） |
| 422 | 内容被安全策略拦截 |
| 429 | 限流（**串行排队**） |
| 5xx | 服务端错误，稍后重试 |
