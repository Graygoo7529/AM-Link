# Agent Memory Add/Search

面向 Agent Memory Leaderboard 的 Add/Search 记忆服务。当前版本同时提供零外部依赖的 Smoke/降级模式，以及固定 `gpt-4o-mini`、`embedding-3` 的增强模式。

完整设计、取舍和后续技术路线见 [设计理念.md](./设计理念.md)。接口字段以主办方的 [Evaluation Protocol](https://agentmemories.ai/evaluation) 和公开 [评测仓库](https://github.com/AML-memory/agent-memory-leaderboard) 为准。

执行状态和可复现验收记录见 [docs/README.md](./docs/README.md)。

## 当前能力

- `POST /v1/memory/add`：在 HTTP 200 前原子提交原始事件、工作记忆和基础检索索引；
- `POST /v1/memory/search`：按 `user_id` 检索证据，返回不超过 `top_k` 的 `data` 数组；
- `GET /health`：无需鉴权；
- 相同 `user_id + request_id` 和相同请求体可安全重试，不重复写入；不同请求体复用同一 ID 返回 HTTP 409；
- 支持 `Authorization: Token`、`Authorization: Bearer`、`X-Api-Key` 和本地无鉴权模式；
- SQLite/WAL 为事务真源，`Memory.md` 与 daily Markdown 是可重建投影。
- Add 增强模式先用 lexical/embedding 召回相关旧节点和 links，再由 `gpt-4o-mini` 生成严格 schema 的 fact proposal，并在同用户事务内应用 entity/concept/fact、typed links、supersede/tombstone 和有效期；
- Search 增强模式先初召回，再让一次 `gpt-4o-mini` 调用同时生成查询计划和候选 ID 偏好，不生成答案；随后融合 FTS、`embedding-3`、逐种子两跳 links 和节点质量特征；
- 结构化节点使用 `canonical_key` 复用同一事实，Search 按 `evidence_group_id` 去重；中文查询补充连续词和二元/三元片段，planner 不可用时仍可确定性识别当前/历史查询；
- Search 图扩展保留最多两跳的 `GraphPath`、关系和 source event 覆盖，并按路径质量参与重排；同源 fact/entity/concept 只占一个结构化结果位置，同时保留直接 raw 证据；
- 英文问句检索会过滤高置信模板词和助动词，减少 `what/did/the` 对 FTS、LIKE 和相关性分数的干扰；
- 消息中的明确日期、相对日、上下周星期和上下月会在有 source timestamp 时解析为保守日期范围，Search 可按该范围召回证据；无锚点时只保留原始时间表达；
- `AML_ENRICHMENT_MODE=sync` 是默认模式；设为 `async` 时 Add 只等待 raw/FTS 硬提交，持久化 worker 后台执行 maintenance/embedding，进程重启后可继续消费 pending/failed job；
- 提供 `python -m aml_memory.replay` 回放工具，可对本地或公网 API 记录 recall@k、MRR、重复率、时间/多跳覆盖、分类型召回、延迟和 provider 调用次数；
- 提供 `python -m aml_memory.locomo` 转换器，可将 LoCoMo 原始 JSON 转为受控的 20-message Add/Search 回放 manifest；LoCoMo 自评记录见 [docs/LoCoMo回放.md](docs/LoCoMo回放.md)。
- raw、结构化节点、FTS、向量和图查询均显式限制 `user_id`；同用户 Add 全流程串行，不同用户可以并行；
- 模型或 embedding 故障时返回 raw/lexical 证据，错误日志只记录用户哈希、请求 ID 和错误类型。

默认关闭外部模型，适合协议 Smoke 和故障降级；正式 Full 配置必须设置 `AML_LLM_ENABLED=true`，确保 Add/Search 都实际调用固定的 `gpt-4o-mini`。增强链路已经实现，但在公开评测回放、64/32 并发压测和官方 Smoke 完成前，仍不应视为最终校准版本。

代理调试时可以显式使用已验证的 `gpt-5.4-mini`，但必须同时打开 `AML_ALLOW_NONOFFICIAL_LLM_MODEL=true`；该开关只用于本地联调，正式 Full 前必须恢复 `gpt-4o-mini` 并关闭开关。

当前实现不使用 pi SDK。Add 和 Search 各使用一次有 schema、并发和超时边界的模型调用；图扩展由确定性代码执行。这样更容易审计模型是否固定、控制成本，并避免自由 Agent 循环突破 1200 秒客户端超时。后续只有在公开回放证明多步 Agent 显著提高召回时才引入，并继续受固定模型、最大步数和总 deadline 约束。

## 本地启动

Python 3.10 及以上：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
$env:AML_AUTH_SCHEME = "bearer"
$env:AML_API_KEY = "local-secret"
$env:AML_LLM_ENABLED = "true"
$env:OPENAI_BASE_URL = "https://api.zhizengzeng.com/v1"
$env:OPENAI_API_KEY = "set-in-your-shell-or-secret-manager"
$env:AML_EMBEDDING_ENABLED = "true"
$env:ZHIPU_API_KEY = "set-in-your-shell-or-secret-manager"
.\.venv\Scripts\python -m aml_memory
```

默认监听 `http://127.0.0.1:8080`。开发环境可将 `AML_AUTH_SCHEME` 设为 `none`；正式提交必须启用鉴权。

## Docker 启动

```powershell
docker build -t aml-memory:0.1.0 .
docker run --rm -p 8080:8080 -v aml-memory-data:/data `
  -e AML_AUTH_SCHEME=bearer `
  -e AML_API_KEY=replace-with-a-long-random-key `
  -e AML_LLM_ENABLED=true `
  -e OPENAI_BASE_URL=https://api.zhizengzeng.com/v1 `
  -e OPENAI_API_KEY=replace-at-runtime `
  -e AML_EMBEDDING_ENABLED=true `
  -e ZHIPU_API_KEY=replace-at-runtime `
  aml-memory:0.1.0
```

镜像使用单个 Uvicorn worker。SQLite 和 Markdown 投影依赖共享本地卷，不能直接横向扩为多个无状态实例；需要横向扩容时应先按设计文档迁移到 PostgreSQL/共享索引。

## Add 示例

```powershell
curl.exe -X POST http://127.0.0.1:8080/v1/memory/add `
  -H "Authorization: Bearer local-secret" `
  -H "Content-Type: application/json" `
  -d '{"request_id":"run-1:chunk-0","messages":[{"role":"user","timestamp":1704067200000,"content":"I will visit Shanghai next Monday."}],"user_id":"run-1:user-0","session_id":"run-1:session-0"}'
```

成功响应：

```json
{
  "success": true,
  "request_id": "run-1:chunk-0",
  "user_id": "run-1:user-0",
  "session_id": "run-1:session-0"
}
```

## Search 示例

```powershell
curl.exe -X POST http://127.0.0.1:8080/v1/memory/search `
  -H "Authorization: Bearer local-secret" `
  -H "Content-Type: application/json" `
  -d '{"query":"Where will the user go next Monday?","options":["Shanghai","Beijing"],"user_id":"run-1:user-0","top_k":100}'
```

Search 返回证据而不是最终答案：

```json
{
  "data": [
    {
      "id": "mem_...",
      "content": "[2024-01-01T00:00:00.000Z][user][session: run-1:session-0] I will visit Shanghai next Monday.",
      "score": 0.85,
      "created_at": "2024-01-01T00:00:00.000Z"
    }
  ]
}
```

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AML_DB_PATH` | `data/aml_memory.db` | SQLite 文件路径 |
| `AML_MARKDOWN_VIEW_DIR` | `data/markdown` | Markdown 投影目录；空字符串可关闭 |
| `AML_AUTH_SCHEME` | `none` | `none`、`token`、`bearer` 或 `x-api-key` |
| `AML_API_KEY` | 空 | 启用鉴权时必填 |
| `AML_MAX_TOP_K` | `100` | 服务端结果上限，最大 100 |
| `AML_WORKING_MEMORY_EVENT_LIMIT` | `40` | 工作记忆保留的近期事件数 |
| `AML_WORKING_MEMORY_CHAR_LIMIT` | `16000` | 工作记忆字符上限 |
| `AML_MAINTENANCE_EVENT_THRESHOLD` | `1` | maintenance 触发所需的未整理事件数；默认 1 保持每次 Add 的正式行为 |
| `AML_MAINTENANCE_CHAR_THRESHOLD` | `1` | maintenance 触发所需的未整理字符数；事件数或字符数任一达到即触发 |
| `AML_ENRICHMENT_MODE` | `sync` | `sync` 或 `async`；async 将模型/embedding 增强移到持久化 worker |
| `AML_ADD_DEADLINE_SECONDS` | `120` | Add 可选增强阶段总预算；raw/FTS 硬提交不受影响 |
| `AML_SEARCH_DEADLINE_SECONDS` | `30` | Search embedding/planner/graph 可选阶段总预算 |
| `AML_LLM_ENABLED` | `false` | 启用 Add maintenance 和 Search query planning；Full 必须为 true |
| `AML_LLM_MODEL` | `gpt-4o-mini` | 比赛模型锁，配置为其他值会拒绝启动 |
| `OPENAI_BASE_URL` | `https://api.zhizengzeng.com/v1` | 智增增 OpenAI 兼容 API 根地址，调用 `/chat/completions` |
| `OPENAI_API_KEY` | 空 | 启用 LLM 时必填，只从环境读取 |
| `AML_LLM_TIMEOUT_SECONDS` | `90` | 单次模型 HTTP 超时 |
| `AML_LLM_MAX_OUTPUT_TOKENS` | `2500` | 单次结构化响应 token 上限 |
| `AML_LLM_MAX_RETRIES` | `2` | 408/425/429/5xx 与网络错误的最大重试次数 |
| `AML_LLM_MAX_CONCURRENCY` | `16` | 进程内模型并发上限 |
| `AML_EMBEDDING_ENABLED` | `false` | 启用 `embedding-3` 向量索引和语义召回 |
| `AML_EMBEDDING_MODEL` | `embedding-3` | embedding 模型锁 |
| `AML_EMBEDDING_DIMENSIONS` | `512` | 向量维度，允许 256 至 2048 |
| `AML_EMBEDDING_BATCH_SIZE` | `64` | 单次 embedding 文本数上限 |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 智谱 API 根地址 |
| `ZHIPU_API_KEY` | 空 | 启用 embedding 时必填，只从环境读取 |

## 测试

```powershell
.\.venv\Scripts\python -m pytest
```

45 项测试覆盖协议响应、Add 后立即 Search、幂等冲突、用户隔离、三种鉴权、相关 maintenance context、结构化维护、失败重试、版本/tombstone、跨用户 mutation 拒绝、候选级 query plan、两跳图扩展、GraphPath 路径传播、向量融合、canonical/evidence 去重、source-event 结构折叠、旧库字段迁移、中文检索、英文问句停用词、时间表达和 temporal Search、planner-free 历史状态过滤、sync/async enrichment、maintenance 阈值批处理、过期失败任务保护、批量失败重试 watermark 推进、deadline 降级、回放指标、LoCoMo 转换、session 切片与脏 evidence 规范化、索引重建、30 天清理、调试模型保护、提供方协议和故障降级。

需要更换 embedding 维度或修复索引时，可在服务停止写入后执行全量或单用户重建。新向量全部计算成功后才会在事务中替换旧索引：

```powershell
$env:AML_EMBEDDING_ENABLED = "true"
$env:ZHIPU_API_KEY = "set-in-your-shell-or-secret-manager"
.\.venv\Scripts\python -m aml_memory.reindex
.\.venv\Scripts\python -m aml_memory.reindex --user-id "opaque-user-id"
```

模型暂时故障后，可在代理恢复且确认该 request 的 raw 数据仍在库中时显式重试 maintenance；普通 Add 重放不会触发重试：

```powershell
$env:AML_LLM_ENABLED = "true"
$env:OPENAI_API_KEY = "set-in-your-shell-or-secret-manager"
.\.venv\Scripts\python -m aml_memory.retry_maintenance `
  --user-id "opaque-user-id" --request-id "eval:run:chunk-0"
```

评测结束后按主办方要求删除原始及派生数据，清理命令必须使用明确的 UTC 截止时间并纳入部署定时任务：

```powershell
.\.venv\Scripts\python -m aml_memory.purge_memory `
  --before "2026-09-07T00:00:00.000Z"
```

## 正式提交检查

- 使用公开仓库与固定 commit，保留本 README、Dockerfile、依赖和方法说明；
- 先运行主办方 Smoke，确认 Add/Search 路径、鉴权头和 Health URL；
- 正式服务启用 HTTPS 和独立 Memory System Key，不把任何 Key 写入镜像；
- 使用持久卷并备份 SQLite；不要使用会丢失本地卷的自动扩缩容；
- Full 前完成第二阶段召回质量验证；正式 Full 的 `top_k` 为 100，客户端可能并发调用并重试；
- 学术自行部署需要按主办方要求保持公网接口稳定可访问；学术代码提交由平台按仓库说明构建，不在仓库中提供 Eval Key。
