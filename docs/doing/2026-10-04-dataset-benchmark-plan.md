# 官方数据集、数据目录与 Add/Search 靶场

日期：2026-10-04；状态：`in_progress`

## 目标

1. 梳理 Agent Memory Leaderboard 第二期公开说明中正式列出的数据集、套件契约和当前公开语料的边界。
2. 新建 `dataset/`，记录原始来源、许可、版本、切分、解析和使用方法；只把允许本地研究的公开原始数据放在 Git 忽略的数据区。
3. 新建 `benchmark/`，以官方 Textual Add/Search JSON 协议驱动不同服务，实现可选数据切片、逐请求追踪、证据排名和结构化结果。
4. 提供 Mem0 开源自托管 REST API 适配器。使用其已部署 HTTP API 进行对照，不下载或构建 Mem0 源码，不在本机运行 Docker。

## 边界与决定

- 参赛记忆系统负责 Add/Search；官方平台负责 Answer/Eval。靶场测量本地证据召回、协议成功率和延迟，不伪称 AML 分数或官方评测结果。
- 官方公开发布仓库提供评测配置/契约，不发布原始语料、保留题、金标答案或私有标注。不得尝试重建或寻找它们。
- 本地公开数据用于记忆方法检验，与 AML 的 Refined/versioned bundle 严格区分；当前只取得 LoCoMo 原始公开源。LongMemEval-S 公开文件约 277 MB，但本机 PowerShell HTTPS 下载在握手阶段失败，先保留确定来源和下载脚本，不提升为已获取。
- 公共实例使用上游许可、署名与删除规则。报告与原始请求、返回证据同样保存在 Git 忽略路径；不默认上报任何外部服务。
- 每个评测 run 对 user_id/request_id/session_id 做 run 命名空间隔离；不共享样本记忆。运行过程默认串行和不自动重试，以便固定次序并暴露故障。
- Add/Search API 不提供内部模型调用数、token 数或费用。未接入被测服务的独立账单/usage 数据时，这些值写为 `null`，不可推断为 0。
- Mem0 选择官方 Mem0 OSS self-hosted REST server。其 API 与 AML envelope 不同，需要薄适配；它不等同于 AML 参赛者 API，也不会因接入云平台而冒充本地开源测量。

## 子计划

| 状态 | 计划 | 验收 |
| --- | --- | --- |
| done | [官方数据集和来源核验](./2026-10-04-dataset-research.md) | 按赛道登记官方展示名、机器 contract ID、可访问源和限制 |
| in_progress | [数据集目录与转换](./2026-10-04-dataset-preparation.md) | LoCoMo 本地 smoke 完成；LongMemEval-S 实际下载/格式核验待 HTTPS 恢复 |
| in_progress | [Add/Search 靶场](./2026-10-04-benchmark-arena.md) | 离线协议与指标验证完成；AM-Link 二期/Mem0 端到端对照待服务可用 |

## 执行记录

| 日期 | 工作 | 结果 |
| --- | --- | --- |
| 2026-10-04 | 读取项目规则、二期调研、一期回放实现与当前 AML / Mem0 官方资料 | 确认比赛正式比较 Add/Search；本地已有可追溯 LoCoMo 原始数据和一期受控回放工具 |
| 2026-10-04 | 检查本地原始 LoCoMo 数据 | 10 对话、272 sessions、5,882 turns、1,986 questions；SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| 2026-10-04 | 创建 `dataset/` 并复制公开 LoCoMo | 新副本 SHA 与历史副本完全一致；固定 `conv-26` smoke 生成 5 Add/6 Search |
| 2026-10-04 | 创建 `benchmark/` 并实现 AML/Mem0 OSS adapters | 已添加协议校验、namespace 隔离、可回查 JSONL trace 与结构化检索指标；Mem0 Add 空结果不再当成功 |
| 2026-10-04 | 离线验证 | dataset 4 项、benchmark 5 项 unittest 通过；compileall 与 CLI help 通过 |
| 2026-10-04 | 尝试访问 LongMemEval-S 上游文件 | HTTPS 握手失败；未创建下载残片，状态保持 `not_downloaded` |

## 总体验收

- [x] `dataset/` 与 `benchmark/` 入口文档说明数据许可、来源、运行方法和成绩限制。
- [x] 至少一个公开切片能生成协议 manifest；LoCoMo 固定切片重复生成一致。
- [x] 不带模型/网络密钥的协议回放测试通过；请求 trace 包含 Search 实际返回的证据正文与 rank。
- [x] official target 严格按 AML Add/Search 路径及响应格式校验；Mem0 adapter 的差异明确记录。
- [x] report/trace schema 含数据版本/hash、目标系统版本、调用数、延迟、错误、证据召回和完整链覆盖；真实服务实测待服务可用。
- [ ] 现有未提交的 `AGENTS.md` 路径编辑保留，验证时单独核对；不提交其他用户内容、数据、数据库、密钥或 runs。

## 尚未完成

- LongMemEval-S 数据下载和上游实际文件格式适配验证受当前出站 HTTPS 限制。
- 没有本地二期实现或已运行的 Mem0 OSS REST 服务；本轮可以核对适配器协议，不执行模型调用、产生外部费用或声称比较分数。
- AML 当前冻结 bundle 的内部精确题目数和完整生成流程不公开；正式绑定前须以平台冻结 contract 为准。
