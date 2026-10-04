# Add/Search 靶场

`benchmark/` 是本地诊断回放器。它读取 `dataset/` 生成的 manifest，按照官方 Textual Add/Search 语义写入每个样本、再逐题检索，输出可复算的证据召回摘要和 JSONL 操作追踪。

它不实现官方 Answer/Eval，不生成答案，也不计算 AML 分数。每次 run 的 manifest SHA、数据集来源、系统名/版本、实际 HTTP 调用数、延迟、错误、每个 query 的证据 rank、候选内容和逐条 Add/Search 请求/响应均在本机 `dataset/data/runs/<run-id>/`。trace 含原文与检索结果，可能还原数据集片段；不要上传、提交或公开该目录。

## 参与对象

| Target | 入口 | 协议 |
| --- | --- | --- |
| 参赛实现/旧接口/其他服务 | `aml-api` | 原样使用官方 `POST /v1/memory/add`、`POST /v1/memory/search` 及严格响应校验 |
| Mem0 OSS self-hosted | `mem0-oss` | 调用 Mem0 REST `POST /memories` 和 `POST /search`；薄适配器将返回候选映射为靶场统一记录 |

AML API 目标的 `base-url` 不含用户名密码、查询或 fragment。鉴权 secret 只通过环境变量读取，不进入 trace/config 文件。Mem0 目标指向已经运行且完成 provider 配置的 Mem0 OSS REST API，不是 Mem0 Platform 云服务。Mem0 OSS API 不带 `/v1/` 前缀；它必须由操作者提供且启用鉴权的 server。本机不安装 Mem0、不获取其源代码、不运行 Docker。Mem0 的运行通常需要外部模型和向量库；连接前应先评估费用与原始数据的去向。

`mem0-oss` 只传它 API 文档明确支持的 `role/content`、`user_id`、`run_id` 和 `top_k`，所以当前 adapter 不保留消息 timestamp，也不携带 AML `request_id` 幂等语义。它和完整 AML 合规接口不是同等输入能力；报告会标出该差异。

## 生成一个公开小切片

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py inspect --dataset locomo
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset locomo --conversation-ids conv-26 --session-limit 4 --category 1 --category 2 --category 3 --questions-per-category 2 --output dataset\data\derived\locomo-smoke.json
```

manifest 建立后，启动一个被测服务，然后将其 URL 填入命令。官方格式参数：

```powershell
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target aml-api `
  --base-url http://127.0.0.1:8080 `
  --system-name AM-Link `
  --system-version local-dev `
  --auth-scheme none
```

从环境读取鉴权 Key 的示例：

```powershell
$env:AM_LINK_MEMORY_KEY = "<local secret>"
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target aml-api `
  --base-url https://memory.example.com `
  --auth-scheme bearer `
  --api-key-env AM_LINK_MEMORY_KEY
```

Mem0 OSS 例子：

```powershell
$env:MEM0_API_KEY = "<mem0 local API key>"
.\.venv\Scripts\python.exe -m benchmark run `
  --manifest dataset\data\derived\locomo-smoke.json `
  --target mem0-oss `
  --base-url http://127.0.0.1:8000 `
  --auth-scheme x-api-key `
  --api-key-env MEM0_API_KEY `
  --system-version "mem0-oss-local"
```

`--case-limit` 和 `--query-limit` 可在运行时对 manifest 再限量；正常情况下从 builder 固定并记录切片条件。不同 target 使用不同 run_id/user_id namespace，不会共享单个样本的存储空间。失败调用不在靶场内重试；修复后换 run_id 得到独立新 run。

## 输出与解读

默认文件在 `dataset/data/runs/<run-id>/report.json` 和 `trace.jsonl`。报告包含 Add/Search 成功率与 p50/p95/max、按 category 分组的 hit@k/evidence recall@k/MRR/multi-evidence chain coverage、空检索结果准确率、重复候选率、错误类型以及每个查询的 target ranks。JSONL 记录保留实际请求 ID、样本、问题、目标 source evidence、返回候选正文、匹配位置和接口状态。

这些指标衡量公开样本的字面/来源证据召回，不是 answer correctness。String target 对语义改写可能漏判，不能独立用于优劣排名；读逐题证据和 query trace，再将同切片结果与上游 benchmark 的任务判据对照。准确性无标注时不计算 precision。官方 Add/Search API 不暴露真实 provider usage/费用，因此相应 report 字段为 `null`，而非 `0`。

## 离线验证

协议校验和指标实现测试无需启动 API 或使用模型：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s benchmark\tests -v
```

靶场当前是顺序本地评估器，不宣称官方并发/容量压测；未来需要按固定 concurrency 与明确预算另行扩展。完整 scope/实施记录见 [主计划](../docs/doing/2026-10-04-dataset-benchmark-plan.md) 和[靶场设计子计划](../docs/doing/2026-10-04-benchmark-arena.md)。
