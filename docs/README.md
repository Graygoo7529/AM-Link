# 项目文档

更新日期：2026-10-14。目标是让新会话快速恢复项目背景和决策依据；旧过程记录留在一期归档中。

| 阅读顺序 | 文档 | 用途 |
| --- | --- | --- |
| 1 | [一期设计理念](./phase-1/design-principles.md) | 不依赖代码名称理解记忆设计 |
| 2 | [一期实验与工程经验](./phase-1/lessons.md) | 接口、数据、效果、架构及重试教训 |
| 3 | [一期收尾记录](./phase-1/closeout.md) | 当前状态、归档边界和已完成事项 |
| 4 | [服务器接入经验](./operations/server.md) | 本地运行、部署和端口服务；2026-10-04 SSH/HTTPS/续期核验 |
| 5 | [模型接入经验](./operations/models.md) | LLM、embedding、配置；2026-10-04 最小真实调用核验 |
| 6 | [二期接入调研](./phase-2/integration-research.md) | 当前官方约定、变化与下一步 |
| 7 | [数据集与 Add/Search 靶场实施](./doing/README.md) | 独立数据层、公开数据获取、靶场双向适配与可观测记录 |
| 8 | [样本与记忆案例分析](../casestudies/README.md) | 持续积累真实案例、处理方法和可核验的实验经验 |
| 9 | [统一研究可视化](../visualization/README.md) | 四视角、26 个案例、会话/网页复用、[可观测性标准接口](../benchmark/OBSERVABILITY.md) |
| 10 | [记忆研究分享报告](./report/README.md) | 面向分享的数据集地图、典型案例、Add/Search 理论链路与 Mem0/AM-Link 真实观测 |
| 11 | [从样本开始设计记忆](./phase-2/memory-design-workbench.md) | 用证据链、时间、归属和遗忘案例决定机制与观测点 |
| 12 | [案例实验与研究工作区](../benchmark/STUDIES.md) | 数据切片、真实运行、自动展示、持久评注与 native 方法接入 |
| 13 | [Add/Search 记忆研究调研综述](./doing/2026-10-08-memory-research-survey.md) | 数据难点分类、Mem0 实例和二期设计建议 |
| 14 | [AM-Link 二期方法实现](../amlink/README.md) | 本地服务、引用图、native 观测与[实施验证](./doing/2026-10-08-amlink-implementation.md) |
| 15 | [Answer 靶场与真实案例复核](./doing/2026-10-08-amlink-answer-research.md) | gpt-5.6-luna 诊断 Answer、逐题后验复核、Add/Search 真实失败位置 |
| 16 | [AM-Link 二期方法改进计划](./phase-2/method-improvement-plan.md) | 结合 TinySoul、案例与当前实现的重构计划；每个 Add 先生成可检索最小 episode，工作区跨请求累积，Search/Reflection 分开 |

最新状态先读[10月14日100题重跑复核](./doing/2026-10-14-amlink-100-rerun-review.md)：完整修复版报告已生成，128/145 Add、100/100 Search；目标Add均成功的94道题上，top-5证据召回约55.3%、完整链约59.6%。Search实测338次Inspect、72次Backlink和787次Select，但Reflection的127次工具决策仍只有Mutation/Stop，没有形成稳定的先探索再整理路径。60项本地回归通过；跨数据集锚点和定向复验见[10月13日扩展验证](./doing/2026-10-13-amlink-expanded-validation.md)。历史完整基线Add 68/145、Search 99/100及旧0.2.0审计分别见[100题诊断](./doing/2026-10-11-amlink-100-rerun-analysis.md)和[核心审计](./doing/2026-10-11-amlink-core-audit.md)。

新增的 Mem0/AM-Link 同条件 Add/Search/Answer 运行见[10月14日真实模型链路补充实验](./doing/2026-10-14-real-model-chain-report.md)：关系组和拒答小例已完成端到端回答，B03 长历史暴露 Add/Reflection 丢批，PersonaMem 暴露失败 Add 仍留下部分可检索状态，C02 暴露 Answer 越过条件证据。分享页[docs/report](./report/README.md)已同步这些案例观察。

`private/` 仅本机存在：包含已授权保存的 SSH 账号、服务器环境快照和模型 Key。公开文档只记录接入方法。

服务器当前保留通用公网基础设施和示例：`https://121.43.49.84/hello`、`https://121.43.49.84/health`，HTTP 也可访问。使用 Let’s Encrypt shortlived 生产 IP 证书及自动续期；它们不属于 AM-Link API。维护方式见[服务器接入经验](./operations/server.md)，服务器上的可读说明位于 `/opt/public-web/README.md`。

一期原始长文从 [归档设计理念](../archive/phase-1/设计理念.md) 和 [历史文档索引](../archive/phase-1/docs/README.md) 查阅。它们保留原貌；尚未完成的旧计划不会自动成为二期任务。
