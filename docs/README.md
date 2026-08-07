# 执行文档目录

本目录记录 Agent Memory Leaderboard Add/Search 方案的事实核对、执行计划和验收结果。状态使用小写英文值，便于后续脚本或 CI 检查：

- `done`：已完成并有可复现验收证据；
- `in_progress`：已开始但验收尚未闭合；
- `todo`：尚未实施；
- `blocked`：被外部信息、账号或基础设施阻塞。

## 文档

| 文档 | 用途 |
| --- | --- |
| [官方要求核对.md](./官方要求核对.md) | 比赛原文、官方公开评测仓库和当前实现的约束核对 |
| [执行计划.md](./执行计划.md) | 分阶段任务、状态、验收标准和依赖 |
| [验收记录.md](./验收记录.md) | 已执行命令、测试结果和残余风险 |
| [提供方与运行模式.md](./提供方与运行模式.md) | 模型/embedding 协议、兼容性假设、调用成本和故障语义 |
| [优化方案.md](./优化方案.md) | Evidence-first 混合记忆的优化架构、数据模型和验收指标 |
| [回放评测.md](./回放评测.md) | Add/Search 回放 manifest、指标定义、命令和 Smoke 记录 |
| [LoCoMo回放.md](./LoCoMo回放.md) | 赛事数据可得性、LoCoMo 转换方法、真实 HTTP baseline 和 embedding 对照状态 |
| [最终优化计划.md](./最终优化计划.md) | TinySoul Memory 机制提炼、最后一轮 Add/Search 优化范围与验收门槛 |
| [扩大验证与可靠性优化.md](./扩大验证与可靠性优化.md) | 10 conversation、正式 provider、并发负载、失败矩阵和后续质量门槛 |
| [../设计理念.md](../设计理念.md) | 完整 Add/Search 设计、数据模型和技术路线 |

## 当前快照

截至 2026-08-07：协议核心、SQLite/WAL 真源、幂等、user_id 隔离、固定 gpt-4o-mini 的 Add/Search 调用、检索约束 maintenance、结构化 fact/version/link、embedding-3 增量索引、inspect-first planning、普通两跳/multi-hop 三跳 graph、evidence group 去重、source evidence 伴随召回、canonical fact key、确定性时间范围、sync/async enrichment job、绝对 deadline、有界失败恢复、worker 异常隔离、稳定同分排序、Markdown 投影和故障降级均已实现并通过 61 项自动化测试。

默认配置仍关闭外部模型，只用于 Smoke/降级；正式 Full 必须启用 LLM。10 conversation lexical 的 399 Add / 480 Search 已在两套全新数据库得到完全一致结果，Recall@10 `0.439438`、MRR `0.292152`；正式 provider 扩大切片 10 Add / 18 Search 全部成功，Recall@10 `0.662037`、MRR `0.618546`。隔离 HTTP 服务完成 64 并发 Add、32 并发幂等重放和 256 并发 Search，均无失败。公网 HTTPS 已部署；赛事固定 Smoke 仍需在官方入口验证，Docker 仍需在具备 Docker CLI 的干净环境实际 build。
