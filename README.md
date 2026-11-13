# comfy-cloud-apis

把各家**云端视频生成 API**封装成 ComfyUI 原生节点。

**请求直连厂商官方域名，不经过任何第三方代理。** API Key 可以只放在环境变量里，
导出工作流时不会带出密钥。

---

## 为什么不用现成的节点包

| 关注点 | 本项目 | 社区集合包（如 comfyui-byokey） |
|---|---|---|
| 代理链路 | 直连 `api.minimaxi.chat` / `ark.cn-beijing.volces.com` / `dashscope.aliyuncs.com` | 部分走 `api.comfy.org` 代理（价格约为官方 1.4–1.6 倍） |
| Key 存储 | **默认走环境变量**，工作流 JSON 不含密钥 | 多数包只有节点输入框，Key 明文随工作流导出 |
| 素材流向 | 图片只发给你选的那一家厂商 | 走官方节点时，图片会先上传到 Comfy 自己的存储 |
| 下载成片 | **不带 Authorization 头**，不给 CDN 泄露 Key | 部分实现会把 Key 一起发给成片 CDN |
| 代码量 | 只做需要的几家，核心层共用 | 37 个节点 / ~6900 行、覆盖 20+ 家，审计成本高 |
| 可审计性 | 全部源码在仓库里，每行都能读 | 需要自己去翻依赖 |

> 本项目不是要替代官方节点，而是提供**一条你完全能审计、且能控制 Key 与数据流向**的路径。

---

## 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/LiangshouX/comfy-cloud-apis.git
```

重启 ComfyUI。节点出现在分类 `cloud/video/*` 下。

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

## 已接入的厂商

| 厂商 | 节点 | 协议 | 默认 base_url | Key 环境变量 |
|---|---|---|---|---|
| **MiniMax H3** | `cloud/video/MiniMax` | V2 | `https://api.minimax.chat`（国际 `api.minimaxi.chat`） | `MINIMAX_API_KEY` |
| **Seedance（豆包）** | `cloud/video/Seedance` | 方舟 v3 | `https://ark.cn-beijing.volces.com/api/v3` | `ARK_API_KEY` |
| **通义万相 Wan** | `cloud/video/Qwen` | 百炼 | `https://dashscope.aliyuncs.com`（国际 `dashscope-intl.aliyuncs.com`） | `DASHSCOPE_API_KEY` |

每个厂商配一个 **任务查询** 节点（`cloud/video/*` 分类下），
用于本地等待超时后续查任务，**避免重复提交导致重复计费**。

各家的端点、模型 ID、计费与限制详见 [`docs/PROVIDERS.md`](docs/PROVIDERS.md)。

---

## 三个厂商的关键差异（踩坑前先看）

| | MiniMax H3 | Seedance | 通义万相 Wan |
|---|---|---|---|
| 本地图片能否内联 base64 | 文档未明确承诺，**建议用公网 URL** | 官方示例全是公网 URL，**建议用 URL** | ✅ **官方明确支持** `data:{MIME};base64,...` |
| 参考角色互斥规则 | 首尾帧 与 reference_* 不能混用 | 同 | 参考音频需搭配图/视频 |
| 成片链接有效期 | 官方未标注 | 官方未标注 | ⚠️ **仅 24 小时**，必须立即下载 |
| 轮询状态词 | queued/running/succeeded/failed/cancelled/expired | queued/running/succeeded/failed | PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED/UNKNOWN |
| 特殊请求头 | — | — | `X-DashScope-Async: enable`（**必须**，否则报"不支持同步调用"） |

---

## 成本记账

每次成功出片都会往 `ComfyUI/output/comfy_cloud_apis/usage.jsonl` 追加一条：

```json
{"ts":"2026-11-14 01:20:33","provider":"MiniMax","model":"MiniMax-H3","resolution":"768P","duration":5,"task_id":"42...","estimated_cost":{"currency":"USD","per_second":0.08,"estimated_total":0.4}}
```

价格表在 `comfy_cloud_apis/core/prices.json`，**随时可改，不用动代码**。
每个条目带 `checked` 核对日期，过期的一眼能看出来；价格缺失时 `estimated_cost` 为 `null`
（**不瞎猜**）。

---

## 目录结构

```
comfy-cloud-apis/
├── __init__.py                  # 插件入口：注册所有节点
├── comfy_cloud_apis/
│   ├── core/
│   │   ├── credentials.py       # Key 解析：节点输入 → 环境变量 → 凭据文件
│   │   ├── http.py              # 异步请求 + 错误翻译（HTTP 码 → 可执行动作）
│   │   ├── media.py             # 图像 tensor ↔ data URI、目录管理
│   │   ├── task.py              # 通用异步轮询器 + 状态归一化
│   │   ├── outputs.py           # VIDEO / IMAGE / AUDIO 类型封装
│   │   ├── usage.py             # 成本估算 + JSONL 记账
│   │   ├── prices.json          # 价格表（可编辑）
│   │   └── base.py              # 节点基类：一套流程复用给所有厂商
│   └── providers/
│       ├── minimax.py
│       ├── seedance.py
│       └── qwen_wan.py
├── docs/
│   ├── PROVIDERS.md             # 各家 API 契约对照
│   ├── SECURITY.md              # 凭据策略与威胁模型
│   └── ROADMAP.md
└── .github/workflows/ci.yml
```

**新增一家厂商** = 在 `providers/` 加一个文件，实现 6 个方法
（`build_payload` / `create` / `fetch` / `status_of` / `video_url_of` / `usage_of`），
其余全部复用基类。

---

## 文档

- [`docs/PROVIDERS.md`](docs/PROVIDERS.md) —— 各家端点、模型、计费、限制、报错码
- [`docs/SECURITY.md`](docs/SECURITY.md) —— 凭据策略、威胁模型、审计结论
- [`docs/ROADMAP.md`](docs/ROADMAP.md) —— 计划中的节点与已知限制

---

## 已知限制

- 节点**未经真实 API 端到端验证**（开发环境没有各家的 Key）。协议依据是各家官方文档，
  CI 只做静态检查与导入冒烟测试。首次使用请先用最便宜的档位跑一条（5 秒 / 最低分辨率）。
- 本地等待超时**不代表云端任务失败**。任务 ID 会落盘在
  `output/comfy_cloud_apis/<厂商>/tasks/<task_id>.json`，用任务查询节点续查，**不要重复提交**。
- 视频生成是**异步**的：官方免费额度下并发任务数很低（MiniMax 文档：免费 2 个 / 付费 15 个），
  批量时请串行排队。

---

## License

MIT
