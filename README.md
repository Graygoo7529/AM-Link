# AM-Link

AM-Link 是一个面向 Agent Memory Leaderboard 的证据优先 Add/Search 记忆服务。它把对话原文作为不可变真源，在其上增量维护 fact、entity、concept、typed links、时间状态和向量索引；Search 返回可审计的记忆证据，不生成最终答案。

当前发布版本：`0.3.0`

项目仓库：[Graygoo7529/AM-Link](https://github.com/Graygoo7529/AM-Link)

赛事参考：[Agent Memory Challenge](https://agentmemories.ai/competition/) · [API/Rules](https://agentmemories.ai/rules)
CI：GitHub Actions 负责在 Linux runner 中构建 Docker；本地开发不需要安装 Docker。

## 项目定位

AM-Link 只负责两件事：

1. `Add`：持久化记忆并完成可检索的内部维护；
2. `Search`：在指定 `user_id` 范围内返回排序后的证据。

最终回答由赛事平台统一生成。服务不会把 query 改写成答案，不读取评测金标，也不在 Search 中运行自由 Agent 循环。

## Add/Search 协议

### Add

`POST /v1/memory/add`，请求字段与赛事同步契约一致：

```json
{
  "request_id": "eval:run_abc123:dataset:conv-0:chunk-0",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "memory text"
    }
  ],
  "user_id": "eval:run_abc123:dataset:conv-0",
  "session_id": "eval:run_abc123:sample:0"
}
```

成功响应必须是 `HTTP 200`，并且只有在原文已经持久化、可立即被 Search 找到后才返回：

```json
{
  "success": true,
  "request_id": "eval:run_abc123:dataset:conv-0:chunk-0",
  "user_id": "eval:run_abc123:dataset:conv-0",
  "session_id": "eval:run_abc123:sample:0"
}
```

同一 `user_id + request_id` 的相同 payload 可安全重放；payload 不同则返回 `409`。服务不返回 `202`、task ID 或轮询地址。

### Search

`POST /v1/memory/search`：

```json
{
  "query": "Which answer best matches the memory?",
  "options": ["A. First answer", "B. Second answer"],
  "user_id": "eval:run_abc123:dataset:conv-0",
  "top_k": 100
}
```

响应必须是按相关性排序的 `data` 数组；无结果时返回空数组。每条结果至少包含非空 `id` 和 `content`，可选 `score`、`created_at`：

```json
{
  "data": [
    {
      "id": "mem_01H...",
      "content": "remembered fact text",
      "score": 0.87,
      "created_at": "2026-07-01T12:00:00Z"
    }
  ]
}
```

正式评测的 `top_k` 为 `100`。`user_id` 是唯一检索隔离边界；`session_id` 只用于来源组织，不作为 Search 过滤条件。

### Health 与鉴权

- `GET /health`：无需鉴权，返回 `{"status":"ok"}`；
- Add/Search 支持 `Authorization: Bearer ...`、`Authorization: Token ...` 和 `X-Api-Key: ...`；
- `AML_AUTH_SCHEME=none` 只适用于本地开发或公开 Smoke，正式服务必须启用独立 Memory System Key；
- 生产 URL 使用 HTTPS，URL 中不包含密钥。

## ADD/SEARCH 架构

### Add 路径

1. 按用户加锁，SQLite/WAL 事务写入 raw event、working memory、daily/FTS；
2. `sync` 模式下调用一次固定 `gpt-4o-mini` maintenance，输出严格校验的 fact/entity/concept/link mutation；
3. Repository 只允许 mutation 引用本轮同用户召回的稳定 ID，并在事务内处理 version、supersedes、tombstone 和 source evidence；
4. 可选调用 `embedding-3`，按 2400 字符分块、200 字符重叠建立向量索引；
5. Markdown 是可重建投影，不是真源。provider 或投影失败时保留 raw/FTS，任务进入可恢复的 enrichment 状态。

### Search 路径

1. FTS/lexical、embedding 和时间候选初召回；
2. planner 前执行一次有界一跳 link inspect；
3. 一次 `gpt-4o-mini` query plan 只产生扩展词、intent 和候选 ID 偏好，不产生答案；
4. 重新执行 lexical/semantic/status 检索，按 intent 进行最多两跳普通图扩展或最多三跳 multi-hop 扩展；
5. 融合 lexical、semantic、temporal、graph、路径质量和节点质量，按 `evidence_group_id` 去重并稳定排序；
6. 返回已保存的 fact/raw/source evidence，不返回内部推理或生成答案。

memory links 在 inspect、GraphPath、fact-source evidence 伴随召回和关系重排中使用。曾测试过的 novelty 互补选择会牺牲真实 provider 的 Recall/MRR，已删除，不属于当前版本。

## 运行模式

| 模式 | LLM | Embedding | 用途 |
| --- | --- | --- | --- |
| Smoke/降级 | 关闭 | 关闭 | 协议、自测、provider 故障时的 lexical 保底 |
| Full 候选 | `gpt-4o-mini` | `embedding-3` | 正式评测前的增强模式 |

正式 Full 使用：

```text
AML_ENRICHMENT_MODE=sync
AML_LLM_ENABLED=true
AML_LLM_MODEL=gpt-4o-mini
AML_EMBEDDING_ENABLED=true
AML_EMBEDDING_MODEL=embedding-3
```

不要把 `AML_ENRICHMENT_MODE=async` 用于官方 Full：async 会在后台执行增强，而官方要求 Add 返回时记忆已经可检索。`gpt-5.4-mini` 或其他模型只允许本地调试，不能用于 Full。

## 配置

所有密钥只从进程环境或部署平台 Secret 注入，不写入仓库、镜像层、SQLite、Markdown 或日志。配置模板见 [.env.example](./.env.example)。

### 存储与服务

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AML_DB_PATH` | `data/aml_memory.db` | SQLite/WAL 真源 |
| `AML_MARKDOWN_VIEW_DIR` | `data/markdown` | Markdown 投影目录；空值关闭 |
| `AML_AUTH_SCHEME` | `none` | `none`、`token`、`bearer`、`x-api-key` |
| `AML_API_KEY` | 空 | 启用鉴权时必填 |
| `AML_MAX_TOP_K` | `100` | 服务端上限，最大 100 |
| `AML_WORKING_MEMORY_EVENT_LIMIT` | `40` | working memory 近期事件上限 |
| `AML_WORKING_MEMORY_CHAR_LIMIT` | `16000` | maintenance 上下文字符上限 |
| `AML_ENRICHMENT_MODE` | `sync` | `sync` 或 `async`；Full 使用 `sync` |
| `AML_ENRICHMENT_MAX_ATTEMPTS` | `5` | enrichment 最大尝试次数 |
| `AML_ADD_DEADLINE_SECONDS` | `120` | Add 可选增强总预算 |
| `AML_SEARCH_DEADLINE_SECONDS` | `30` | Search 可选增强总预算 |

### LLM 与 embedding

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AML_LLM_ENABLED` | `false` | 启用 Add maintenance 和 Search planner |
| `AML_LLM_MODEL` | `gpt-4o-mini` | 赛事模型锁 |
| `OPENAI_BASE_URL` | `https://api.zhizengzeng.com/v1` | OpenAI-compatible `/chat/completions` 根地址 |
| `OPENAI_API_KEY` | 空 | LLM provider key |
| `AML_LLM_TIMEOUT_SECONDS` | `90` | 单次 provider HTTP 超时 |
| `AML_LLM_MAX_OUTPUT_TOKENS` | `2500` | 结构化输出预算 |
| `AML_LLM_MAX_RETRIES` | `2` | provider 有界重试次数 |
| `AML_LLM_MAX_CONCURRENCY` | `16` | 进程内 LLM 并发上限 |
| `AML_EMBEDDING_ENABLED` | `false` | 启用语义索引和召回 |
| `AML_EMBEDDING_MODEL` | `embedding-3` | embedding 模型锁 |
| `ZHIPU_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 智谱 `/embeddings` 根地址 |
| `ZHIPU_API_KEY` | 空 | embedding provider key |
| `AML_EMBEDDING_DIMENSIONS` | `512` | 允许 256 至 2048 |
| `AML_EMBEDDING_BATCH_SIZE` | `64` | 单批文本数上限 |
| `AML_EMBEDDING_TIMEOUT_SECONDS` | `60` | embedding HTTP 超时 |
| `AML_EMBEDDING_MAX_RETRIES` | `2` | embedding 有界重试次数 |
| `AML_EMBEDDING_MAX_CONCURRENCY` | `32` | 进程内 embedding 并发上限 |

## 本地开发

要求 Python 3.10+。本地开发和协议 Smoke 不需要 Docker：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
$env:AML_AUTH_SCHEME = "none"
$env:AML_DB_PATH = "B:\tmp\aml-memory-dev.db"
$env:AML_LLM_ENABLED = "false"
$env:AML_EMBEDDING_ENABLED = "false"
.\.venv\Scripts\python -m aml_memory
```

默认监听 `http://127.0.0.1:8080`。开发完成后可用 `curl.exe` 调用上面的 Add/Search 路径。不要把 provider key 写入 PowerShell 历史、源码或 `.env` 文件。

## Docker 与 CI

Dockerfile 使用单个 Uvicorn worker 和 `/data` 持久卷。官方代码提交要求 Docker 启动说明，但本地开发不要求安装 Docker；仓库的 GitHub Actions 会在 Linux runner 中执行真实 build。

```bash
docker build -t aml-memory:0.3.0 .
docker run --rm -p 8080:8080 -v aml-memory-data:/data \
  -e AML_AUTH_SCHEME=bearer \
  -e AML_API_KEY=replace-at-runtime \
  -e AML_LLM_ENABLED=true \
  -e OPENAI_API_KEY=replace-at-runtime \
  -e AML_EMBEDDING_ENABLED=true \
  -e ZHIPU_API_KEY=replace-at-runtime \
  aml-memory:0.3.0
```

不要在 `docker build` 时传入任何 key；所有密钥只在 `docker run`、systemd Secret 或平台 Secret 中注入。SQLite 不能通过多个无状态副本共享写入；横向扩容前应迁移到共享事务数据库和向量索引。

## 公网自部署

自部署 API 需要：

- 公网可访问的 HTTPS Add/Search URL 和无需鉴权的 Health URL；
- 独立 Memory System Key；
- `AML_ENRICHMENT_MODE=sync`、`AML_LLM_ENABLED=true`、固定 `gpt-4o-mini`；
- SQLite/Markdown 持久盘、备份、证书自动续期和服务重启策略；
- 提交后至少 30 天保持稳定，并在评测结束后 30 天内删除评测数据及派生副本。

当前部署实例（用于 API 参赛路线）：

```text
Health:  https://121.43.49.84/health
Add:     https://121.43.49.84/v1/memory/add
Search:  https://121.43.49.84/v1/memory/search
Auth:    Authorization: Bearer <Memory System Key>
Version: 0.3.0
```

不要在公开材料中写入 Memory System Key、Eval/Leaderboard Key 或 provider key。Eval/Leaderboard Key 只用于赛事网站创建 Smoke/Full 任务；Memory System Key 只用于平台访问 Add/Search。

## 测试与评测

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m compileall -q src
.\.venv\Scripts\python -m pip check
```

当前仓库有 61 项自动化测试，覆盖协议、鉴权、幂等、user 隔离、maintenance mutation、时间、links、embedding、provider deadline/retry、并发、失败恢复、LoCoMo 转换和降级。LoCoMo 回放工具：

```powershell
.\.venv\Scripts\python -m aml_memory.locomo --help
.\.venv\Scripts\python -m aml_memory.replay --help
```

公开 LoCoMo 只能作为自评，不替代主办方 Smoke/Full。Full 受理后版本冻结，不能因为结果不理想替换实现。

## 原创性与来源披露

AM-Link 是参赛者 **Graygoo7529** 的原创实现，当前仓库中的 Python、SQLite、FastAPI、maintenance、retrieval、GraphPath、provider 适配和部署代码均为本项目独立编写。

设计灵感来自参赛者正在开发的另一个个人原创 Agent 项目 **TinySoul-Agent**。TinySoul-Agent 不是第三方依赖，也没有把其源代码、私有数据、密钥或运行服务复制进本仓库；本项目只在设计层面提炼并重新实现了以下思想：稳定 memory link 身份、先 inspect/recall 再 mutation、source evidence 可追溯、结构化记忆生命周期和 Markdown 可解释投影。AM-Link 针对比赛的 Add/Search 合同重新设计了 FastAPI/SQLite/WAL、固定模型调用、事务边界、user 隔离、provider deadline/retry、降级和评测回放，不是 TinySoul-Agent 的代码打包或接口移植。

LoCoMo 仅用于本地自评，原始数据和评测答案不进入提交仓库；相关来源和许可证记录在 [docs/LoCoMo回放.md](./docs/LoCoMo回放.md)。赛事私有数据不在本项目中保存或硬编码。

## 参赛提交清单

1. 提交 Evaluation Access Request，选择 `Textual Memory`、`Academic Methods` 和自部署 API；
2. 提供固定版本、公开仓库、Add/Search/Health URL、鉴权方式和运行说明；
3. 审核通过后取得 Eval/Leaderboard Key，运行官方 Smoke；
4. Smoke 通过后固定 commit、模型、provider 配置和 Run Label，再提交唯一 Full；
5. 保持公网服务稳定至少 30 天，保留必要审计信息并按官方要求删除评测数据；
6. 提交材料中披露原创性、TinySoul-Agent 的个人原创关系、LoCoMo 来源和所有第三方 provider/依赖。

完整设计和执行记录：

- [设计理念.md](./设计理念.md)
- [docs/README.md](./docs/README.md)
- [docs/官方要求核对.md](./docs/官方要求核对.md)
- [docs/提供方与运行模式.md](./docs/提供方与运行模式.md)
- [docs/验收记录.md](./docs/验收记录.md)
