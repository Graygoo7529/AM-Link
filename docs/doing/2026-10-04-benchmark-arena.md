# Add/Search 靶场设计与实施

日期：2026-10-04；状态：`in_progress`

## 目标与接口

- 靶场把数据 manifest 驱动成串行 HTTP Add/Search 回放器；参赛服务直接使用官方 `POST /v1/memory/add` 与 `POST /v1/memory/search`。
- Mem0 对照对象只接已有 Mem0 OSS self-hosted REST API：`POST /memories` 与 `POST /search`。本项目不拉取/构建 Mem0 源码，不安装 Mem0，不用 Docker，也不自动调用任何云模型。
- 两个适配器共用标准化响应，但报告保留原始服务响应与 Mem0 评分 metadata。Mem0 adapter 检查 Add 有 memory result ID，Search 使用 `explain=true`，并注明它丢失 message timestamp 和 AML `request_id` 幂等语义。

## 可观测与数据隔离

- 默认每个 run 使用独立 `user_id/request_id/session_id` 前缀，不混用 target 的样本空间。运行可通过固定 manifest、`--case-limit`、`--query-limit` 控制规模。
- `report.json` 保存数据 SHA、slice、目标系统名/版本、实际 Add/Search 次数、成功率、延迟分位数、错误、证据召回/完整链覆盖、重复结果及 provider usage（未知时 `null`）。
- `trace.jsonl` 保存每次请求/响应、样本和问题、预期来源证据、返回候选正文、匹配的 target index/rank、耗时与状态码，可逐题回查。
- 默认产物放在 Git 忽略的 `dataset/data/runs/<run-id>/`。其中可恢复原始语料片段；不上传、不提交。鉴权值从环境变量读取，不能写进 run report。
- 不在 benchmark 内重试。失败须原样记为失败；HTTP 200 本身不足以证明上游 provider usage、费用或各项增强成功。

## 指标解释

靶场测的是来源/文本证据召回，包括 `evidence_recall@k`、`hit_rate@k`、`chain_coverage@k`、MRR、空结果诊断、重复候选比例与延迟。LoCoMo/LongMemEval 的目标证据以原始标注映射到写入 history 的 turn 为准；字符串命中对改写有漏判，需查看 trace。它不生成答案、不评价答案正确性、不计算 AML 官方分数，也不能在 API 不公开时推断模型调用数与费用。

## 已实施和验证

- `benchmark/` 有 `aml-api` 与 `mem0-oss` target、manifest 校验器、串行执行器、运行隔离、report/JSONL trace 和 CLI。
- `benchmark/tests/` 的 6 项离线测试通过：官方路由/鉴权、AML 非 200 Add 判失败、结构化 HTTP 错误保留、Mem0 payload scope、Mem0 空写入结果判错、score_details 归一化，以及完整 trace/rank/链覆盖。无需启动服务或模型。
- `dataset/tests/` 的 4 项转换测试通过；LoCoMo 固定切片 smoke 已实际生成 5 Add/6 Search。
- `compileall benchmark dataset` 和两个 CLI `--help` 均通过。

## 后续核验

- [ ] 被测 AM-Link 二期服务可用后，使用本地 LoCoMo smoke 运行一次端到端，核对 Add 可立即 Search 和报告。
- [ ] Mem0 OSS REST server 必须由使用者提供已运行实例与 provider 配置后再对照。当前没有已运行服务/API key，因此没有取得 Mem0 比较成绩，也未发生模型调用/费用。
- [ ] 需要容量/并发结果时另建固定并发和预算方案；当前只做顺序功能/召回诊断。

## 相关

- 数据目录：[dataset/README](../../dataset/README.md)
- 官方数据集边界：[调研](./2026-10-04-dataset-research.md)
- 上游 Mem0 OSS REST API 文档：<https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx>
