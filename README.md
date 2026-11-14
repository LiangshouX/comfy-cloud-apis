# comfy-cloud-apis

把各家**云端视频 / 图像生成 API**封装成 ComfyUI 原生节点。

**请求直连厂商官方域名，不经过任何第三方代理。** API Key 可以只放在环境变量里，
导出工作流时不会带出密钥。

所有推理都在云端完成，本地只做节点编排与文件收发 ——
**没有 GPU 的机器同样能跑**（详见[无 GPU 运行](#无-gpu--低配机器运行)）。

---

## 为什么不用现成的节点包

| 关注点 | 本项目 | 社区集合包（如 comfyui-byokey） |
|---|---|---|
| 代理链路 | 直连 `api.minimaxi.chat` / `ark.cn-beijing.volces.com` / `dashscope.aliyuncs.com` | 部分走 `api.comfy.org` 代理（价格约为官方 1.4–1.6 倍） |
| Key 存储 | **默认走环境变量**，工作流 JSON 不含密钥 | 多数包只有节点输入框，Key 明文随工作流导出 |
| 素材流向 | 图片只发给你选的那一家厂商 | 走官方节点时，图片会先上传到 Comfy 自己的存储 |
| 下载成片 | **不带 Authorization 头**，不给 CDN 泄露 Key | 部分实现会把 Key 一起发给成片 CDN |
| 代码量 | 11 个节点、核心层共用，审计成本低 | 37 个节点 / ~6900 行 / 覆盖 20+ 家，审计成本高 |
| 可审计性 | 全部源码在仓库里，每行都能读 | 需要自己去翻依赖 |

> 本项目不是要替代官方节点，而是提供**一条你完全能审计、且能控制 Key 与数据流向**的路径。

---

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/LiangshouX/comfy-cloud-apis.git
```

重启 ComfyUI。节点出现在分类 `cloud/video/*` 与 `cloud/image/*` 下。

**无额外依赖**：只用 ComfyUI 自带的 `aiohttp` / `numpy` / `torch` / `PIL`，不需要 `pip install`。

---

## 凭据配置

**推荐：环境变量。** 节点的 `api_key` 输入框留空即可。

```powershell
# Windows PowerShell（永久生效）
[Environment]::SetEnvironmentVariable("MINIMAX_API_KEY",  "你的key", "User")
[Environment]::SetEnvironmentVariable("ARK_API_KEY",      "你的key", "User")
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY","你的key", "User")
```
```bash
# Linux / macOS
export MINIMAX_API_KEY="你的key"
export ARK_API_KEY="你的key"
export DASHSCOPE_API_KEY="你的key"
```

设置后**重启 ComfyUI**。节点在控制台会打印当前用的是哪个来源（不会打印 Key 本身）。

也支持本地凭据文件（已在 `.gitignore` 中）：

```json
// ComfyUI/user/comfy_cloud_apis_credentials.json
{ "minimax": "...", "seedance": "...", "qwen": "..." }
```

---

## 已接入的节点

### 视频（`cloud/video/*`）

| 厂商 | 节点 | 协议 | 默认 base_url | Key 环境变量 |
|---|---|---|---|---|
| **MiniMax H3** | `CloudVideo_MiniMaxH3` | V2 | `https://api.minimax.chat`（国际 `api.minimaxi.chat`） | `MINIMAX_API_KEY` |
| **Seedance（豆包）** | `CloudVideo_Seedance` | 方舟 v3 | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_KEY` |
| **通义万相 Wan** | `CloudVideo_QwenWan` | 百炼 | `https://dashscope.aliyuncs.com`（国际 `dashscope-intl.aliyuncs.com`） | `DASHSCOPE_API_KEY` |

### 图像（`cloud/image/*`）

| 厂商 | 节点 | 协议 | 同步/异步 | 模型 |
|---|---|---|---|---|
| **MiniMax** | `CloudImage_MiniMax` | 旧 `/v1/image_generation` + 新 `/v1/images/generations` | 同步 | `image-01` / `image-01-live` / **`MiniMax-H3-Image`** / `MiniMax-H3-Image-Highspeed` |
| **Seedream（即梦）** | `CloudImage_Seedream` | 方舟 v3 | 同步 | `doubao-seedream-5-0-260128` 等 5 个 |
| **千问 Qwen-Image** | `CloudImage_Qwen` | 百炼 multimodal-generation | 同步 | `qwen-image-3.0-pro` / `qwen-image-2.0-pro` 等 7 个 |
| **通义万相 Wan** | `CloudImage_WanT2I` | 百炼 image-synthesis | **异步** | `wan2.6-t2i` / `z-image-turbo` 等 7 个 |

生图节点输出 **IMAGE 列表**（一次请求可出多张），同时给出每张图的本地路径。

异步节点额外配一个**任务查询**节点（`cloud/image/Qwen` 分类下），
用于本地等待超时后续查任务，**避免重复提交导致重复计费**。

各家的端点、模型 ID、计费与限制详见 [`docs/PROVIDERS.md`](docs/PROVIDERS.md)。

---

## 无 GPU / 低配机器运行

**这套节点的全部计算都在云端**，本地只做三件事：

1. 拼请求体（发提示词、URL）
2. 轮询任务状态
3. 下载结果文件 + 转成 ComfyUI 的 IMAGE / VIDEO 类型

所以本地**不需要显卡**，ComfyUI 本身跑 CPU 模式即可：

```bash
python main.py --cpu          # 强制 CPU
```

要点：

| 项 | 说明 |
|---|---|
| 显存 | 本项目不占显存。模型权重根本不在你机器上。 |
| 内存 | 主要是 ComfyUI 自身开销（模型节点越多越大）。只跑本插件的话，4GB 内存够用。 |
| 磁盘 | 只有下载的结果文件。视频 5 秒 768P 约 2–5MB；4K 图片 1–8MB。 |
| 依赖 | `torch` / `numpy` / `PIL` 是 ComfyUI 的硬依赖，CPU 版 torch 也能跑（只做像素转换，不做推理）。 |
| 网络 | 结果文件从厂商 CDN 拉回，跨境线路慢时等待会变长。 |

**适合的场景**：NAS / 家用小主机 / 瘦客户端 / 别人的闲置服务器，
把 ComfyUI 当成"云端模型的调度器"用。

**不适合的场景**：要跑本地 SD、Flux、Wan 权重 —— 那还是得看显存。

---

## 三个厂商的关键差异（踩坑前先看）

### 视频

| | MiniMax H3 | Seedance | 通义万相 Wan |
|---|---|---|---|
| 本地图片能否内联 base64 | 文档未明确承诺，**建议用公网 URL** | 官方示例全是公网 URL，**建议用 URL** | ✅ **官方明确支持** `data:{MIME};base64,...` |
| 参考角色互斥规则 | 首尾帧 与 reference_* 不能混用 | 同 | 参考音频需搭配图/视频 |
| 成片链接有效期 | 官方未标注 | 官方未标注 | ⚠️ **仅 24 小时**，必须立即下载 |
| 轮询状态词 | queued/running/succeeded/failed/cancelled/expired | queued/running/succeeded/failed | PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED/UNKNOWN |
| 特殊请求头 | — | — | `X-DashScope-Async: enable`（**必须**，否则报"不支持同步调用"） |

### 图像

| | MiniMax H3-Image | MiniMax image-01 | Seedream | Qwen-Image | 通义万相 文生图 |
|---|---|---|---|---|---|
| 接口形态 | 同步 | 同步 | 同步 | 同步 | **异步**（需 `X-DashScope-Async`） |
| 端点 | `/v1/images/generations` | `/v1/image_generation` | `/images/generations` | `multimodal-generation` | `image-synthesis` |
| 参考图内联 base64 | ✅ `images[].image_url` | ✅ `subject_reference` | ✅ 明确支持 | ✅ content 里传 image | 不支持（纯文生图） |
| 参考图张数 | **1–16** | **只支持 1** | ≤14 | 1 | — |
| 反向提示词 | ❌ **传了直接被拒** | — | — | ✅ `negative_prompt` | — |
| 提示词上限 | 32000 字符 | 1500 字符 | 建议 300 汉字 | 800–1300 Token | — |
| 最大分辨率 | **16MP**（4096×4096） | 2048 | 4K | 2048×2048 | 1440×1440 |
| 组图多张 | `n` (1–10) | `n` (1–9) | `max_images` (1–15) | `n` (1–6) | `n` (1–4) |
| 联网搜索 | — | — | ✅ 仅 5.0（`tools`） | — | — |
| 计价 | **按 token** | 按张 | 按张 | 按张 | 按张 |
| 结果有效期 | ⚠️ 24 小时 | ⚠️ 24 小时 | ⚠️ 24 小时 | ⚠️ 24 小时 | ⚠️ 24 小时 |

> ⚠️ **MiniMax 的两套生图接口不通用**：端点、参数、响应结构、模型族、计价方式全都不一样。
> 详见 [`docs/PROVIDERS.md` 的 5.0 节](docs/PROVIDERS.md#50-minimax-有两套完全不同的生图接口2026-11-14-补充)。
>
> ⚠️ **H3-Image 端点不幂等**：请求发出后服务器会跑完并计费，即使你本地超时。
> 重试 = 重复计费。本项目已把该模型的请求超时设为 720 秒（服务器上限 600 秒）。

> ⚠️ **四家的图片链接都只有 24 小时有效期。** 本项目在任务成功后**立即下载到本地**，
> 不依赖链接长期有效。

---

## 成本记账

每次成功出片/出图都会往 `ComfyUI/output/comfy_cloud_apis/usage.jsonl` 追加一条：

```json
{"ts":"2026-11-14 01:20:33","provider":"MiniMax","model":"MiniMax-H3","resolution":"768P","duration":5,"task_id":"42...","estimated_cost":{"currency":"USD","per_second":0.08,"estimated_total":0.4}}
```

生图按张计价：

```json
{"ts":"2026-11-14 01:21:10","provider":"Seedream","model":"doubao-seedream-4-0-250828","images":2,"estimated_cost":{"currency":"CNY","per_image":0.2,"images":2,"estimated_total":0.4}}
```

价格表在 `comfy_cloud_apis/core/prices.json`，**随时可改，不用动代码**。
每个条目带 `checked` 核对日期，过期的一眼能看出来；价格缺失时 `estimated_cost` 为 `null`
→（**不瞎猜**）。生图模型的分辨率各家写法不同（`1:1` / `2K` / `2048*2048`），
查不到时自动回退到该模型的 `default` 档。

---

## 目录结构

```
comfy-cloud-apis/
├── __init__.py                  # 插件入口：注册所有节点
├── comfy_cloud_apis/
│   ├── core/
│   │   ├── credentials.py       # Key 解析：节点输入 → 环境变量 → 凭据文件
│   │   ├── http.py              # 异步请求 + 错误翻译（HTTP 码 → 可执行动作）
│   │   ├── media.py             # 图像 tensor ↔ data URI、格式嗅探、目录管理
│   │   ├── task.py              # 通用异步轮询器 + 状态归一化
│   │   ├── outputs.py           # VIDEO / IMAGE / AUDIO 类型封装
│   │   ├── usage.py             # 成本估算（按秒/按张）+ JSONL 记账
│   │   ├── prices.json          # 价格表（可编辑）
│   │   └── base.py              # 节点基类：视频与生图共用一套流程
│   └── providers/
│       ├── minimax.py           # 视频：MiniMax H3
│       ├── minimax_image.py     # 生图：MiniMax image-01
│       ├── seedance.py          # 视频：Seedance
│       ├── seedream.py          # 生图：Seedream（即梦）
│       ├── qwen_wan.py          # 视频：通义万相 Wan
│       ├── qwen_image.py        # 生图：千问 Qwen-Image
│       └── wan_image.py         # 生图：通义万相 文生图（异步）
├── docs/
│   ├── PROVIDERS.md             # 各家 API 契约对照
│   ├── SECURITY.md              # 凭据策略与威胁模型
│   └── ROADMAP.md
├── tests/                       # 47 项协议与逻辑测试（不触网）
└── .github/workflows/ci.yml
```

**新增一家厂商** = 在 `providers/` 加一个文件，实现几个方法
（`build_payload` / `create` / `task_id_of` / `fetch` / `status_of` / `results_of` / `usage_of`），
其余全部复用基类。视频与生图共用同一个 `CloudNodeCommon` 骨架。

---

## 文档

- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) —— 各家端点、模型、计费、限制、报错码
- [`docs/SECURITY.md`](docs/SECURITY.md) —— 凭据策略、威胁模型、审计结论
- [`docs/ROADMAP.md`](docs/ROADMAP.md) —— 计划中的节点与已知限制

---

## 已知限制

- 节点**未经真实 API 端到端验证**（开发环境没有各家的 Key）。协议依据各家官方文档，
  CI 只做静态检查与协议构造测试。首次使用请先用最便宜的档位跑一条（最低分辨率 / 1 张）。
- 本地等待超时**不代表云端任务失败**。任务 ID 会落盘在
  `output/comfy_cloud_apis/<厂商>/tasks/<task_id>.json`，用任务查询节点续查，**不要重复提交**。
- 视频生成是**异步**的：官方免费额度下并发任务数很低（MiniMax 文档：免费 2 个 / 付费 15 个），
  批量时请串行排队。
- 四家的图片链接**都只有 24 小时有效**，本项目会立即下载，但如果你手动取用链接请注意时效。

---

## License

MIT
