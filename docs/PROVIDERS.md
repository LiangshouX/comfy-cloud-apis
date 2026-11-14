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

---

# 5. 生图接口

## ⚠️ 5.0 MiniMax 有两套完全不同的生图接口（2026-11-14 补充）

这是 MiniMax 生图最容易踩的坑：**两套接口的端点、参数、响应结构、模型族全都不一样**，
社区文档里经常混着写。

| | 旧接口（image-01 系列） | 新接口（H3-Image 系列） |
|---|---|---|
| 文生图端点 | `POST {base}/v1/image_generation`（**单数**） | `POST {base}/v1/images/generations`（**复数**） |
| 编辑端点 | 无（`subject_reference` 走同一端点） | `POST {base}/v1/images/edits` |
| 模型 | `image-01` / `image-01-live` | `MiniMax-H3-Image` / `MiniMax-H3-Image-Highspeed` |
| 响应 `data` | **对象**：`data.image_urls` | **数组**：`data[].url` |
| 失败表达 | HTTP 200 + `base_resp.status_code != 0` | HTTP 200 + `data[i].error`（**逐项**） |
| prompt 上限 | 1500 字符 | 32000 字符 |
| n 上限 | 9 | 10 |
| 参考图 | `subject_reference`，**只支持 1 张** | `images[].image_url`，**最多 16 张** |
| 尺寸表达 | `aspect_ratio`（固定 8 个）或 `width`+`height`（512–2048，8 的倍数） | `size="WxH"` **或** `aspect_ratio`+`area`（三者互斥） |
| 提示词增强 | `prompt_optimizer`（默认关） | 默认**开**，`disable_prompt_enhanced` 关闭 |
| 计价 | 按张 | **按 token** |
| 幂等性 | — | ❌ **不幂等**：超时也会计费，重试重复计费 |

### 域名

| 地域 | 域名 |
|---|---|
| 国内（推荐） | `https://api.minimax.cn` |
| 国际 | `https://api.minimax.io` |
| 旧国内 | `https://api.minimax.chat`（仍可用） |
| 旧国际 | `https://api.minimaxi.chat`（仍可用） |

### 新接口（H3-Image）

```http
POST {base}/v1/images/generations
```

```json
{
  "model": "MiniMax-H3-Image",
  "prompt": "An orange cat lying on a windowsill basking in the sun",
  "size": "2720x1536",
  "n": 1,
  "response_format": "url"
}
```

或按比例 + 清晰度（**与 size 互斥**）：

```json
{"model": "MiniMax-H3-Image", "prompt": "...", "aspect_ratio": "16:9", "area": "2K"}
```

响应：

```json
{"created": 1792308678,
 "data": [{"url": "https://.../output-0.jpg", "size": "2720x1536", "revised_prompt": "..."},
          {"error": {"code": "1027", "message": "output image failed content safety check"}}],
 "output_format": "jpeg",
 "usage": {"generated_images": 1, "total_tokens": 7254,
           "input_tokens": 3174, "output_tokens": 4080,
           "input_tokens_details": {"text_tokens": 3174, "image_tokens": 0},
           "output_tokens_details": {"image_tokens": 4080}},
 "request_id": "021792308678142a2c883cf675b9804d"}
```

### ⚠️ 三个必须注意的点

1. **端点不幂等**：请求一旦发出，服务器会跑完并计费，即使客户端超时或断开。
   重试 = 重复生成 + 重复计费。→ 客户端超时必须 ≥600 秒（本项目设 720 秒）。
2. **`size` 与 `aspect_ratio`/`area` 互斥**：设了 `size="WxH"` 再带 `aspect_ratio`
   （连 `"auto"` 都不行）会返回 400。
3. **`disable_prompt_enhanced=true` 时必须给尺寸**：`size` 或具体 `aspect_ratio`，
   否则 400（因为 auto 依赖提示词增强来决定比例）。

### 尺寸表（16MP 档）

| 宽高比 | 2K | 4K（16MP） |
|---|---|---|
| 1:1 | 2048x2048 | 4096x4096 |
| 4:3 / 3:4 | 2368x1760 / 1760x2368 | 4736x3552 / 3552x4736 |
| 16:9 / 9:16 | 2720x1536 / 1536x2720 | 5472x3072 / 3072x5472 |
| 21:9 | 3552x1184 / 1184x3552 | 7104x2368 / 2368x7104 |

面积范围 655,360 – 20,000,000 px，宽高比 1:3 – 3:1。

### 编辑端点

```http
POST {base}/v1/images/edits
```

```json
{"model": "MiniMax-H3-Image",
 "prompt": "Replace the cat in image 1 with the Shiba Inu in image 2",
 "images": [{"image_url": "https://example.com/cat.jpg"}],
 "size": "auto"}
```

`image_url` 支持公网 URL、`mm_file://{file_id}`、`data:image/<格式>;base64,...`。
参考图 1–16 张，**总请求体 ≤ 64 MiB**（base64 约为原文件的 4/3，
图片多时优先用 URL）。单文件 ≤ 64 MiB，宽高 [128, 8192]，比例 ≤ 4:1。

编辑接口**总是**应用提示词增强，`disable_prompt_enhanced` 无效。

### 硬约束（写错直接 400）

| 参数 | 约束 |
|---|---|
| `num_inference_steps` | 只能 6 或省略 |
| `guidance_scale` | 只能 1 或省略（模型无 CFG） |
| `negative_prompt` | **不支持**，传了被拒 |
| `seed` | 整数；配合 `generator_device=cpu` 可跨机器复现 |

### 计价（2026-11-11 核对，按 1M token）

| | 文本输入 | 图像输入 | 图像输出 |
|---|---|---|---|
| `MiniMax-H3-Image` | $2.30 | $1.50 | $3.80 |
| `MiniMax-H3-Image-Highspeed` | $2.30 | $3.00 | $7.60 |

官方给的单张示例价：

| Size | Standard | Highspeed |
|---|---|---|
| 1K | $0.02179 | $0.03529 |
| 2K | $0.02333 | $0.03622 |
| 4K | $0.06879 | $0.13001 |

人民币口径（国内开放平台）：1K ¥0.1430/张、2K ¥0.1531/张、
4K ¥0.4522/张（首周折后 ¥0.2261）。

> 因为按 token 计，**同样的分辨率成本是浮动的**——官方没公布"每张图多少 token"的公式，
> 只有上表的经验值。精确成本以厂商账单为准。

### H3-Image 本地部署门槛（供对照）

权重 68.65GB（DiT）+ 66.7GB（H3 文本编码器）+ 2.34GB（图像 VAE）= **约 138GB**。
单张消费级显卡跑不动——这也是走 API 路径的理由。



四家生图接口的**接口形态不一样**，这是最容易踩坑的地方：

| 厂商 | 端点 | 同步/异步 | 必需请求头 |
|---|---|---|---|
| MiniMax | `POST {base}/v1/image_generation` | **同步** | — |
| Seedream | `POST {base}/images/generations` | **同步** | — |
| Qwen-Image | `POST {base}/api/v1/services/aigc/multimodal-generation/generation` | **同步** | — |
| 通义万相 文生图 | `POST {base}/api/v1/services/aigc/text2image/image-synthesis` | **异步** | `X-DashScope-Async: enable` |

base_url 沿用视频节点：MiniMax `https://api.minimax.cn`（国际 `https://api.minimax.io`，
旧域名 `api.minimax.chat` / `api.minimaxi.chat` 仍可用）、
方舟 `https://ark.cn-beijing.volces.com/api/v3`、百炼 `https://dashscope.aliyuncs.com`
（国际 `dashscope-intl.aliyuncs.com`，推荐业务空间专属域名）。

> MiniMax 视频与生图的 base_url 是同一套域名体系，详见 [5.0](#50-minimax-有两套完全不同的生图接口2026-11-14-补充)。

---

## 5.1 MiniMax image-01

```http
POST {base}/v1/image_generation
```

```json
{
  "model": "image-01",
  "prompt": "A girl looking into the distance from a library window",
  "aspect_ratio": "16:9",
  "response_format": "url",
  "n": 2,
  "seed": 42,
  "prompt_optimizer": false,
  "aigc_watermark": false,
  "subject_reference": [{"type": "character", "image_file": "https://.../person.jpg"}]
}
```

响应：

```json
{"id": "03ff3cd0820949eb8a410056b5f21d38",
 "data": {"image_urls": ["https://..."]},
 "metadata": {"success_count": 1, "failed_count": 0},
 "base_resp": {"status_code": 0, "status_msg": "success"}}
```

`response_format: "base64"` 时改成 `data.image_base64`（数组）。

### ⚠️ 业务错误藏在 HTTP 200 里

`base_resp.status_code` 非 0 就是失败，**必须单独检查**，否则会拿到"成功但没有图片"的空响应：

| 码 | 含义 |
|---|---|
| 1008 | 余额不足 |
| 1026 | 内容涉敏 |
| 2013 | 参数异常 |

### 参数约束

| 参数 | 约束 |
|---|---|
| `prompt` | ≤ 1500 字符 |
| `n` | 1–9 |
| `aspect_ratio` | 1:1 / 16:9 / 4:3 / 3:2 / 2:3 / 3:4 / 9:16 / 21:9 |
| `width` / `height` | 512–2048 且为 8 的倍数；**仅 image-01**；与 aspect_ratio 同时给时 aspect_ratio 优先 |
| `subject_reference` | **只支持 1 张**；`image_file` 支持公网 URL 或 `data:image/...;base64,...` |
| `style` | **仅 image-01-live**；`style_type` = 漫画/元气/中世纪/水彩，`style_weight` (0,1] |

---

## 5.2 Seedream（即梦同源）

```http
POST {base}/images/generations
```

```json
{
  "model": "doubao-seedream-4-0-250828",
  "prompt": "一只戴着墨镜的橘猫，坐在海边，日落，超写实。",
  "size": "2K",
  "response_format": "url",
  "sequential_image_generation": "auto",
  "sequential_image_generation_options": {"max_images": 4},
  "watermark": false,
  "image": ["https://.../1.png", "https://.../2.png"]
}
```

响应：

```json
{"model": "doubao-seedream-4-0-250828", "created": 1757321139,
 "data": [{"url": "https://...", "size": "2048x2048"}],
 "usage": {"generated_images": 1, "output_tokens": 16280, "total_tokens": 16280}}
```

`response_format: "b64_json"` 时 `data[].b64_json`。

### 模型能力对照

| 模型 ID | 文生图 | 参考图 | 组图 | 流式 | 联网搜索 | output_format | seed | guidance_scale | 分辨率 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|
| `doubao-seedream-5-0-lite-260128` | ✓ | ≤14 | ✓ | ✓ | ✓ | png/jpeg | — | — | 2K / 3K |
| `doubao-seedream-5-0-260128` | ✓ | ≤14 | ✓ | ✓ | ✓ | png/jpeg | — | — | 2K / 3K |
| `doubao-seedream-4-5-251128` | ✓ | ≤14 | ✓ | ✓ | — | — | — | — | 2K / 4K |
| `doubao-seedream-4-0-250828` | ✓ | ≤10 | ✓ | ✓ | — | — | — | — | 1K / 2K / 4K |
| `doubao-seedream-3-0-t2i-250415` | ✓ | **不支持** | — | — | — | — | ✓ | ✓ | 1024×1024 |

### 约束

- 「参考图数 + 生成张数 ≤ 15」
- `image` 支持公网 URL、URL 数组、base64（`data:image/<格式>;base64,...`，格式名小写）
- `size` 可写 `1K`/`2K`/`3K`/`4K` 或具体像素如 `2048x2048`
- `optimize_prompt_options.mode` = `standard`（更准更慢）/ `fast`
- 提示词建议 ≤ 300 汉字 / 600 英文单词
- IPM 限流：500 张/分
- 图片 URL **仅 24 小时有效**

---

## 5.3 千问 Qwen-Image（百炼 multimodal-generation）

```http
POST {base}/api/v1/services/aigc/multimodal-generation/generation
```

```json
{
  "model": "qwen-image-2.0-pro",
  "input": {
    "messages": [{
      "role": "user",
      "content": [{"text": "冬日北京的都市街景..."}]
    }]
  },
  "parameters": {
    "negative_prompt": "低分辨率,肢体畸形,过度光滑",
    "size": "2048*2048",
    "n": 1,
    "prompt_extend": true,
    "watermark": false,
    "seed": 42
  }
}
```

响应：

```json
{"output": {"choices": [{"finish_reason": "stop",
  "message": {"role": "assistant",
              "content": [{"image": "https://dashscope-result-....png?Expires=..."}]}}]},
 "usage": {"image_count": 1, "width": 2048, "height": 2048},
 "request_id": "d0250a3d-..."}
```

### 模型对照

| 模型 ID | 文生图 | 编辑 | 张数 | 分辨率 | 格式 |
|---|:-:|:-:|---|---|---|
| `qwen-image-3.0-pro` | ✓ | ✓ | 1–6 | 自由，总像素 512²–2048² | png |
| `qwen-image-3.0` | ✓ | ✓ | 1–6 | 同上 | png |
| `qwen-image-2.0-pro` | ✓ | ✓ | 1–6 | 同上 | png |
| `qwen-image-2.0` | ✓ | ✓ | 1–6 | 同上 | png |
| `qwen-image-max` | ✓ | — | **固定 1** | 1664×928 等预设比 | png |
| `qwen-image-plus` | ✓ | — | **固定 1** | 同上 | png |
| `qwen-image` | ✓ | — | **固定 1** | 同上 | png |

### 约束

- `size` 格式是 `宽*高`（不是 `16:9`）
- `n` 对 max/plus/base 固定为 1，2.0 系列可到 6
- 提示词：2.0 系列 ≤ 1300 Token，其他 ≤ 800 Token；**只支持一个 text**
- `negative_prompt` ≤ 500 字符
- **仅 `qwen-image` / `qwen-image-plus` 支持异步接口**，本项目走同步
- **API 当前仅支持返回 URL，不支持 base64 输出**
- 图片 URL **仅 24 小时有效**

---

## 5.4 通义万相 文生图（异步）

```http
POST {base}/api/v1/services/aigc/text2image/image-synthesis
X-DashScope-Async: enable
```

```json
{
  "model": "wan2.6-t2i",
  "input": {"prompt": "一只小猫在草地上奔跑，电影感，光影自然"},
  "parameters": {
    "size": "1024*1024",
    "n": 1,
    "prompt_extend": true,
    "watermark": false,
    "seed": 42
  }
}
```

创建响应：

```json
{"request_id": "5dbf9dc5-...", "output": {"task_id": "7277e20e-...", "task_status": "PENDING"}}
```

查询 `GET {base}/api/v1/tasks/{task_id}`：

```json
{"output": {"task_id": "...", "task_status": "SUCCEEDED",
            "results": [{"url": "https://dashscope-result-....png?Expires=..."}]},
 "usage": {"image_count": 1}}
```

### 模型

`wan2.6-t2i` / `wan2.5-t2i-preview` / `wan2.2-t2i-plus` / `wan2.2-t2i-flash` /
`wan2.1-t2i-plus` / `wan2.1-t2i-turbo` / `z-image-turbo`

### 约束

- `size` 格式 `宽*高`，宽高均在 [512, 1440]，最大 200 万像素
- `n` 1–4
- `prompt_extend` 开启会额外增加 3–4 秒
- **纯文生图**（图像编辑走 Qwen-Image / Seedream 节点）
- 状态词：`PENDING` / `RUNNING` / `SUCCEEDED` / `FAILED` / `CANCELED` / `UNKNOWN`
