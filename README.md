# AM-Link

AM-Link 是一个面向 Agent Memory Leaderboard 的证据优先 Add/Search 记忆服务。
当前版本：`0.3.0`。服务只负责写入和检索记忆，最终答案由评测平台生成。

- 仓库：[Graygoo7529/AM-Link](https://github.com/Graygoo7529/AM-Link)
- 参赛代码基线：`0.3.0` / commit `1881abe`（后续提交仅更新说明文档）
- 当前公网实例：`https://121.43.49.84`
- 赛事：[Agent Memory Challenge](https://agentmemories.ai/competition/)

## API

| 用途 | 地址 | 鉴权 |
| --- | --- | --- |
| Health | `GET https://121.43.49.84/health` | 无需鉴权 |
| Add | `POST https://121.43.49.84/v1/memory/add` | `Authorization: Bearer <Memory System Key>` |
| Search | `POST https://121.43.49.84/v1/memory/search` | `Authorization: Bearer <Memory System Key>` |

Add 使用赛事同步协议：请求包含 `request_id`、`messages`、`user_id`、`session_id`，只有原文已持久化且可检索时才返回 `200`。Search 请求包含 `query`、可选 `options`、`user_id` 和 `top_k`，返回排序后的 `data` 证据数组。完整字段以 [docs/官方要求核对.md](./docs/官方要求核对.md) 和 [models.py](./src/aml_memory/models.py) 为准。

## 从仓库运行

要求 Python 3.10+。本地开发不需要 Docker：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
$env:AML_AUTH_SCHEME = "none"
$env:AML_DB_PATH = "B:\tmp\aml-memory-dev.db"
$env:AML_LLM_ENABLED = "false"
$env:AML_EMBEDDING_ENABLED = "false"
.\.venv\Scripts\python -m aml_memory
```

默认监听 `http://127.0.0.1:8080`。正式 Full 使用环境变量或 Secret 注入：

```text
AML_AUTH_SCHEME=bearer
AML_API_KEY=<memory-system-key>
AML_ENRICHMENT_MODE=sync
AML_LLM_ENABLED=true
AML_LLM_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.zhizengzeng.com/v1
OPENAI_API_KEY=<llm-provider-key>
AML_EMBEDDING_ENABLED=true
AML_EMBEDDING_MODEL=embedding-3
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4
ZHIPU_API_KEY=<embedding-provider-key>
```

配置模板见 [.env.example](./.env.example)。密钥不得写入仓库、镜像、数据库或日志。

## Docker

本地不要求安装 Docker；GitHub Actions 会在 Linux runner 中构建并启动容器 smoke。具备 Docker 的环境可执行：

```bash
docker build -t aml-memory:0.3.0 .
docker run --rm -p 8080:8080 -v aml-memory-data:/data \
  -e AML_AUTH_SCHEME=bearer \
  -e AML_API_KEY="<memory-system-key>" \
  -e AML_ENRICHMENT_MODE=sync \
  -e AML_LLM_ENABLED=true \
  -e AML_LLM_MODEL=gpt-4o-mini \
  -e OPENAI_API_KEY="<llm-provider-key>" \
  -e AML_EMBEDDING_ENABLED=true \
  -e AML_EMBEDDING_MODEL=embedding-3 \
  -e ZHIPU_API_KEY="<embedding-provider-key>" \
  aml-memory:0.3.0
```

所有密钥只在运行时注入；SQLite 数据保存在 `/data`，镜像使用单个 Uvicorn worker。

## Add/Search 封装位置

- HTTP 路由和 FastAPI 应用：[src/aml_memory/api.py](./src/aml_memory/api.py)
- 请求/响应模型：[src/aml_memory/models.py](./src/aml_memory/models.py)
- Add/Search 编排：[src/aml_memory/service.py](./src/aml_memory/service.py)
- SQLite/WAL、FTS、向量和 memory links：[src/aml_memory/repository.py](./src/aml_memory/repository.py)
- LLM/embedding provider：[src/aml_memory/providers.py](./src/aml_memory/providers.py)

## 原始方法与技术报告

完整设计报告是 [设计理念.md](./设计理念.md)，执行和验收材料见 [docs/README.md](./docs/README.md)。核心方法是：

1. 将 raw conversation 作为不可变证据，以 SQLite/WAL 事务维护结构化 fact、entity、concept 和 source evidence；
2. 使用固定 `gpt-4o-mini` 做 Add maintenance 和 Search query planning，使用 `embedding-3` 做语义索引；
3. 使用 typed memory links、时间状态、GraphPath 和 evidence-group 去重增强关系、多跳和时序检索；
4. 以 `user_id` 隔离数据，使用幂等、deadline、有限重试和 lexical fallback 保证异常可用性；
5. Search 只返回保存的证据，不生成答案，不运行无界 Agent 循环。

## 做过的方法改动

- 从基础 raw/FTS 检索扩展为 raw、结构化节点、向量和 links 的混合检索；
- 增加版本、supersedes、tombstone、source evidence、时间范围和稳定排序；
- 增加 inspect-first、普通两跳和 multi-hop 三跳 GraphPath；
- 增加 provider 超时、退避重试、并发上限、失败恢复和降级；
- 实测发现 novelty/互补 evidence selector 会降低真实 provider 的 Recall/MRR，已从正式版本删除；
- 当前正式配置固定为 `gpt-4o-mini` + `embedding-3` + `AML_ENRICHMENT_MODE=sync`，不使用 pi SDK。

AM-Link 是 **Graygoo7529** 的原创实现。设计灵感来自同一作者的个人原创项目 **TinySoul-Agent**；TinySoul-Agent 不是第三方依赖，本仓库没有复制其源代码、私有数据、密钥或运行服务，仅独立重实现相关设计思想。LoCoMo 只用于本地自评，不进入正式服务或提交数据。

## 验证

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m compileall -q src
.\.venv\Scripts\python -m pip check
```

当前仓库 61 项自动化测试通过。LoCoMo 转换和回放工具：

```powershell
.\.venv\Scripts\python -m aml_memory.locomo --help
.\.venv\Scripts\python -m aml_memory.replay --help
```

参赛时固定版本为 `0.3.0`；Smoke 通过后不要更改代码、模型、provider 或公网接口，正式 Full 受理后版本冻结。
