# Add/Search 本地靶场

比赛平台通常只给正式系统一次评测机会。`benchmark/` 的目标是在本地用固定公开数据、官方参赛 Add/Search contract 和本地 trace 反复检查候选实现，再决定是否提交正式评测。它会模拟官方给参赛者发 Add/Search 的边界和调用顺序；公开数据和本地 evidence 规则是可复核的替代评估集，不能声称是官方冻结题集、Answer/Eval 或官方成绩。

靶场按 manifest 顺序把一个样本的历史送入 Add，再发送其 Search 问题。`aml-api` 原样调用 `POST /v1/memory/add`、`POST /v1/memory/search` 并严格核对协议响应。Mem0 有两个适配入口：`mem0-library` 直接调用已发布的 Python package `mem0ai`；`mem0-oss` 调用已运行的 Mem0 OSS self-hosted REST API (`POST /memories`、`POST /search`)。不把 Mem0 源码复制进仓库或自行构建；当前环境禁用 Docker，因此示例优先使用 Python package adapter。每个 target 获得新的 run/user namespace，不能共享样本状态。

## 选数据和控制规模

每个 manifest 固定数据源、SHA、切分条件和 builder version；可以为不同数据集生成独立 manifest，也可按 conversation/question/category/session 切分。运行时还可用 `--case-limit`、`--query-limit` 限量。正式对比时要让两个 target 使用同一 manifest 与同一切片；新 run 会生成新 namespace。

当前可生成 LoCoMo 和 LongMemEval-S manifest：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset locomo --conversation-ids conv-26 --session-limit 4 --category 1 --category 2 --category 3 --questions-per-category 2 --output dataset\data\derived\locomo-smoke.json
```

LongMemEval-S 的历史和逐题文件约 277 MB；如果本地已取得，可以只选一个问题和 8 个 session 做低成本检索检查：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset longmemeval-s --question-limit 1 --session-limit 8 --output dataset\data\derived\longmemeval-smoke.json
```

其他已找到的数据源及许可/读取方式见 [`dataset/`](../dataset/README.md)。它们接入前不会误选为支持的 converter。限制后的切片不是该数据集全量成绩。

## 运行对照

准备 AM-Link/候选 Add/Search 服务后，直接指定 `aml-api`：

```powershell
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target aml-api `
  --base-url http://127.0.0.1:8080 `
  --system-name AM-Link `
  --system-version local-dev
```

Mem0 package adapter 是可选项，不会由靶场自动安装。官方默认配置使用外部 OpenAI 模型和 embedding 服务，因此会把公开 history 发送给所配置的 provider 并可能计费；只有确认数据去向与预算后才运行。也可以配置 Mem0 支持的本地 provider：

```powershell
.\.venv\Scripts\python.exe -m pip install mem0ai
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target mem0-library `
  --system-name Mem0 `
  --system-version "<installed mem0ai version>"
```

这个 adapter 调用 Python `Memory.add` / `Memory.search`，不会访问官方 API server，也不带 AML `request_id` 幂等语义，当前不传逐消息 timestamp；报告会记录这些能力差异。它使用当前 Python 环境中已安装的官方发布包，不下载或构建 Mem0 源码。

如果 HTTP target 要求 key，从环境变量读取，绝不写入 report 或 trace：

```powershell
$env:AM_LINK_MEMORY_KEY = "<local secret>"
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target aml-api `
  --base-url https://memory.example.com `
  --auth-scheme bearer `
  --api-key-env AM_LINK_MEMORY_KEY `
  --system-version local-dev
```

如果已运行并配置好 Mem0 OSS REST server，也可以使用 REST target：

```powershell
$env:MEM0_API_KEY = "<mem0 local API key>"
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target mem0-oss `
  --base-url http://127.0.0.1:8000 `
  --auth-scheme x-api-key `
  --api-key-env MEM0_API_KEY `
  --system-version mem0-oss-local
```

Mem0 Python 与 REST contract 都不包含 AML 的 `request_id` 幂等字段；当前 adapters 也不传消息 timestamp，报告会标明这些差异。未运行的目标不会自动启动，也不会自动配置外部模型。Mem0 官方 quickstart 和 REST API 文档见 [Python SDK Quickstart](https://github.com/mem0ai/mem0/blob/main/docs/open-source/python-quickstart.mdx) 与 [REST API Server](https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx)。

## 查看单个失败

默认 run 文件在被忽略的 `dataset/data/runs/<run-id>/report.json` 和 `trace.jsonl`。报告含 Add/Search 成功率、延迟、每题 rank、evidence recall/hit/chain coverage、错误计数及 diagnosis 计数。trace 保留原始请求/响应、证据正文、dataset source id、result rank、HTTP 状态和耗时；可能复原原始样本，仅保存在本地。

按样本 case ID 或具体 Search ID 展开报告和关联 trace：

```powershell
.\.venv\Scripts\python.exe -m benchmark inspect `
  --report dataset\data\runs\<run-id>\report.json `
  --trace dataset\data\runs\<run-id>\trace.jsonl `
  --case-id conv-26
```

LoCoMo/LongMemEval 的每个 evidence target 都关联原始 turn/session 和对应 Add request。诊断优先检查 Search 是否成功、该证据所属 Add 是否成功、目标原文是否在 Search 返回项中按字面匹配、匹配 rank 是否在前五；报告也提供 query、top_k、错误响应和候选内容，方便定位。

诊断是可观察接口边界上的证据，不是对 target 私有内部状态的断言。`no_literal_evidence_match` 表示原始证据字串/ID 未出现在返回结果，可能是丢失，也可能是被摘要/改写，需人工对照返回内容。仅凭 Add 200 或 Search 200 不推断 memory 完整、准确、模型调用成功或费用为零。API 不公开的 usage/费用记录为 `null`。

当前靶场严格按顺序回放，不在内部自动重试；一个公开样本的 evidence recall 不是端到端问答准确率。LoCoMo、LongMemEval 原文与其 evidence 标注、公开的上游 Answer judge，以及 AML 私有 bundle 都是不同对象。后续如要跑答案级评估，应新增明确的 evaluator adapter，把 rubric/答案留在写入路径外，且独立记录 judge/model 与真实费用。

## 离线验证

无需启动服务或模型：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s benchmark\tests -v
.\.venv\Scripts\python.exe -m benchmark --help
.\.venv\Scripts\python.exe -m benchmark inspect --help
```

设计和实施状态见[靶场子计划](../docs/doing/2026-10-04-benchmark-arena.md)与[总计划](../docs/doing/2026-10-04-dataset-benchmark-plan.md)。
