# 安全模型

本项目存在的理由之一就是**让密钥与素材的流向完全可读、可控**。
这份文档把做过的取舍写下来，方便 review。

---

## 1. 凭据处理

### 优先级

```
节点 api_key 输入框  >  环境变量  >  ComfyUI/user/comfy_cloud_apis_credentials.json
```

**推荐做法**：把 `api_key` 输入框**留空**，只用环境变量。
这样导出的工作流 JSON 里不含任何密钥，可以放心分享。

代码位置：`comfy_cloud_apis/core/credentials.py`

### 硬性约束

| 约束 | 实现 |
|---|---|
| 日志里不打印 Key | 只打印**来源**（`env:MINIMAX_API_KEY`），不打印值 |
| 任务记录里不落 prompt 原文 | `_payload_summary()` 只保留 `content_roles` 与标量参数 |
| 凭据文件不入库 | `.gitignore` 已排除 `*_credentials.json` 与 `.env` |
| Key 不发给 CDN | 下载成片时**不附带** `Authorization` 头 |

### 节点输入框填 Key 的风险

ComfyUI 的工作流是明文 JSON。`api_key` 输入框里填了 Key，**导出的 .json 里就有 Key**，
分享工作流 = 分享 Key。所以这个输入框只是为了方便临时调试，长期使用请走环境变量。

---

## 2. 数据流向

| 数据 | 去向 |
|---|---|
| 提示词、参考图/视频/音频 URL | **只有你填的 base_url 那一家厂商** |
| 本地图像 | 若走内联 base64 → 直接进请求体；若走 URL → 只传 URL 字符串 |
| 成片 | 厂商 CDN → **下载到你的本地** `ComfyUI/output/` |

**不做的事**：不向任何第三方回传数据、不打点、不上报、不写用户目录以外的配置。

---

## 3. 与官方节点的关键差异

**ComfyUI 官方 MiniMax 节点会把你的图片上传到 Comfy 自己的存储**
（`upload_images_to_comfyapi()`），再把 Comfy 生成的 URL 传给 MiniMax。

如果你处理的是客户未公开素材，这条链路需要额外评估。
本项目的直连实现不存在这一环。

另外，官方节点走 `api.comfy.org` 代理，价格约为厂商直连的 **1.4–1.6 倍**
（官方节点价格徽章：H3 768P $0.1287/s、2K $0.1859/s；厂商直连 $0.08 / $0.13）。

---

## 4. 代码审计结论（2026-11-13）

对社区包 `MeteorAndy/comfyui-byokey`（master 分支，2026-11-13 拉取复核）做了逐文件扫描，
作为"自己写 vs 用现成"的决策依据。记录在此供对照。

**规模**：27 个 `.py` 文件 / 6,871 行 / 37 个节点类 / 覆盖 20+ 家厂商 API 域名。

**干净的部分**：

- 全仓**无** `eval` / `exec` / `__import__` / `subprocess` / `os.system` / `ctypes` / `pickle.loads`
- 硬编码域名**全部是各厂商自己的 API 主机**（`api.minimax.chat` / `ark.cn-beijing.volces.com` /
  `dashscope.aliyuncs.com` / `api.klingai.com` / `api.openai.com` 等），**无第三方回传域名**
- **不读任何环境变量**（全仓无 `getenv` / `os.environ`）
- **不写任何配置或凭据文件**——唯一的写操作是用 `av` 把成片封装成输出产物
- import 仅 `PIL / aiohttp / asyncio / av / base64 / comfy_api / concurrent / io / json / logging / numpy / torch / uuid`，
  全部 ComfyUI 自带，**没有隐藏的 pip install**

**三个需要注意的点**：

1. **没有环境变量支持** —— `api_key` 是节点输入框，保存工作流时**明文写入 JSON**。
2. **它的 MiniMax 节点不是 H3** —— 实现的是 V1 Hailuo 契约
   （`/v1/video_generation`、`T2V-01`/`I2V-01`、顶层 `prompt`、三段式取文件），
   与 H3 的 V2 协议不兼容。
3. **下载成片时把 `Authorization` 头一起发给了 CDN 下载地址** ——
   `nodes_minimax.py` 里是 `download_video_output(download_url, headers=headers, ...)`，
   而 `headers` 含 `Authorization: Bearer <key>`，`download_url` 是厂商 CDN 域名。
   Key 会因此出现在第三方 CDN 的请求日志里。

---

## 5. 已知风险与缓解

| 风险 | 缓解 |
|---|---|
| Key 随工作流泄露 | 默认走环境变量；README 与节点 tooltip 明确提示 |
| 本地等待超时后重复提交导致重复计费 | task_id 落盘 + 提供任务查询节点；超时错误信息里直接给出 task_id 与"勿重复提交"提示 |
| 并发超限 | 文档与报错都提示串行；节点默认轮询间隔 15 秒 |
| 请求体超限（64MB） | 图片优先走 URL；报错提示 413 的成因 |
| 素材被厂商留存 | 敏感素材请用**本地权重**部署，或选择有明确数据条款的厂商方案 |

---

## 6. 报告问题

发现任何问题请开 issue，**请不要在 issue 里贴 API Key**。
如果确实需要复现，请用假 Key 并说明是哪一步失败。
