# Add/Search 靶场设计与实施

日期：2026-10-04；状态：`done`（本地靶场实现和离线验收完成；真实目标端到端比较待服务/模型配置）。

## 为什么建靶场

比赛正式环境只提供一次测评机会，所以在此之前需要本地重复验证候选实现，并尽可能复刻参赛系统的 Add/Search 交互边界。每次本地 run 必须固定公开数据 manifest 和选样本，便于 AM-Link 与 Mem0 对照并复核。同一靶场不能声称掌握官方的私有语料/Answer/Eval 结果：本地分数是公开源诊断，不是正式 leaderboard score。

## 流程与目标

```text
公开数据 + 固定切片
        |
        v
官方 Textual Add/Search manifest
        |
        +----> AM-Link/兼容实现  POST /v1/memory/add, POST /v1/memory/search
        |
        +----> Mem0 Python package adapter Memory.add / Memory.search
        +----> Mem0 OSS REST adapter POST /memories, POST /search
        |
        v
report.json + trace.jsonl + per-case inspection
```

- Add 与 Search 按 manifest 顺序执行，每个 case 独立 user；每个 run 添加 `user_id/request_id/session_id` 前缀，避免复用旧记忆。靶场不自动重试。
- `aml-api` 适配器严格校验官方 Add/Search status 和 response shape。Mem0 可走已发布的 `mem0ai` Python package 或 OSS REST API；两者都是薄适配器，报告记录其没有 AML `request_id` 幂等语义且当前不传 message timestamp。
- 可以更换 target 复用同一 manifest；manifest builder 支持数据选择，CLI 另有 `--case-limit`/`--query-limit`。报告记录 source SHA、slice、target、version、真实 Add/Search 调用数、延迟和错误。
- 靶场不自动安装依赖或调用模型。操作者可显式安装已发布 `mem0ai` package 并配置其 provider；REST target 则须自行提供已启动的 OSS API。没有目标就只做离线测试，不宣称获得对照分数。Mem0 源码不会复制进仓库或自行构建；本地禁用 Docker。

## 逐样本追踪与可归因范围

- 每个证据目标保留其上游 record/turn/session 或 turn index，以及写入该 source turn 的原始 Add `request_id`。
- `report.json` 的 query row 提供 target rank 和 diagnosis；`trace.jsonl` 保存实际 Add/Search 请求与响应、HTTP/contract error、延迟、完整候选内容、target/evidence 匹配关系。
- `python -m benchmark inspect --report ... --trace ... --case-id <sample>` 展开整个 case；`--search-id <query>` 展开一题及相关 source Add event。
- 已实现可观察边界的分类：Search 失败、source Add 失败、没有字面 source fragment/ID 匹配、字面命中但低于 top 5、top 5 内命中。report 按类型汇总，trace 仍保留 rank/source/error 便于人工分析。
- `no_literal_evidence_match` 不等于 memory 一定丢失；它可能是摘要/改写导致字串变化。没有目标内部日志时，靶场只能判断外部输入、请求结果和返回证据，不能断言私有写入/检索/模型内部哪一步失败。
- Provider usage 不在 API 可见时写 `null`，不从 HTTP 200 推断成功增强、准确性或零费用。trace 可还原样本内容，只在本机 Git ignored runs 保存。

## 当前评测规则

当前 LoCoMo / LongMemEval retrieval diagnostic 用公开标注源 turn 对返回内容做 literal evidence match，报告 `evidence_recall@k`、`hit_rate@k`、`chain_coverage@k`、MRR、空检索和重复候选、Add/Search 成功率与延迟。语义改写可能产生字面 false negative，需在 inspect 视图人工核对。

Answer/rubric QA 不是当前执行链。LongMemEval 有作者答案 judge；CLBench、PersonaMem、BEAM 也分别有自己的 answer/rubric 评估逻辑。接入时必须创建隔离的 evaluator stage，gold/rubrics 永不进入 Add/Search 输入，并记录 judge/model、调用数、延迟和真实费用。

## 已实施和离线检查

- [x] `aml-api`、`mem0-library` 与 `mem0-oss` adapters、请求/响应 contract 校验、target errors、run namespace、顺序 replay。
- [x] JSON 报告与逐请求 JSONL trace，包括 source SHA/slice、请求/响应、原文证据和结果 rank。
- [x] evidence target 来源链扩展到对应 source Add request，供逐样本原因分析。
- [x] `inspect` 支持 case 或 search ID，关联对应 source Add 与 Search events。
- [x] dataset 4 项、benchmark 9 项单元测试通过；`compileall` 和 CLI `--help` 通过；单测注入 Add 503 并确认 inspect 展开关联 source Add/Search event。
- [ ] AM-Link 二期服务可用后跑小切片端到端；Mem0 Python package/REST 有实例且模型/费用预算已知后再做对照。当前无已运行服务或模型调用。
- [ ] 要测并发/容量时需独立设置固定 concurrency、请求量和模型预算；当前是串行功能与证据诊断。

## 文件索引

- [`README.md`](../../benchmark/README.md)：target 配置、运行和单样本 inspect。
- [`core.py`](../../benchmark/core.py)：协议验证、回放、指标和 diagnosis。
- [`targets.py`](../../benchmark/targets.py)：官方 API 与 Mem0 Python/REST targets。
- [数据转换计划](./2026-10-04-dataset-preparation.md)
