# 项目文档

更新日期：2026-10-26。目标是让新会话快速恢复项目背景和决策依据；旧过程记录留在一期归档中。

| 阅读顺序 | 文档 | 用途 |
| --- | --- | --- |
| 1 | [一期设计理念](./phase-1/design-principles.md) | 不依赖代码名称理解记忆设计 |
| 2 | [一期实验与工程经验](./phase-1/lessons.md) | 接口、数据、效果、架构及重试教训 |
| 3 | [一期收尾记录](./phase-1/closeout.md) | 当前状态、归档边界和已完成事项 |
| 4 | [服务器接入经验](./operations/server.md) | 本地运行、部署和端口服务；2026-10-04 SSH/HTTPS/续期核验 |
| 5 | [模型接入经验](./operations/models.md) | LLM、embedding、配置；10月23日网络权限复核成功；后续冻结输入诊断出现间歇超时，详见最新报告 |
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
| 17 | [P0/P1证据链与Reflection执行细则](./phase-2/evidence-loop-execution-plan.md) | 五包已接入；[实施核对](./doing/2026-10-23-evidence-loop-implementation.md)记录回归、真实切片、失败与尚未达成的质量验收 |

2026-10-26 最新先读[证据窗口与分步Reflection报告](./doing/2026-10-26-evidence-and-draft-implementation.md)和[执行计划](./phase-2/2026-10-26-evidence-and-draft-plan.md)。默认链路修复片段和可见来源，分步协议默认关闭、独立实测。LM4由“未展示价格”推进到“已展示仍被Select排除”；新人物历史与完整人物材料的失败单列，整体方法未验收、未部署。此前23个问题/1385次调用见[10月24日报告](./doing/2026-10-24-broad-method-implementation.md)。

此前阶段：2026-10-23 先读[闭环实施与真实复验](./doing/2026-10-23-reflection-convergence-implementation.md)及[执行计划核对](./phase-2/reflection-convergence-plan.md)：140项回归通过，新增220次真实调用。统一可见范围、目标正文保留、关系阻断反馈、缓冲误触发修复已实施；真实Select/查询扩展在历史图副本上执行，但当前构图仍不稳定、整体方法未验收。LLM装箱合法但来源覆盖6/7，确定性为7/7，维持默认。未扩大20/100题、未部署。[之前的复核](./doing/2026-10-23-reflection-convergence-audit.md)与[前轮实施核对](./doing/2026-10-23-evidence-loop-implementation.md)保留为过程记录；8项旧跟踪测试产物仍待处理。

历史验证见[10月14日100题重跑复核](./doing/2026-10-14-amlink-100-rerun-review.md)和[10月15日证据链修复记录](./doing/2026-10-15-evidence-chain-repair.md)：完整修复版为128/145 Add、100/100 Search；目标Add均成功的94道题上，top-5证据召回约55.3%、完整链约59.6%。Search实测338次Inspect、72次Backlink和787次Select；新的 Reference 互补片段、证据闭合和 Reflection 先看再写门槛已完成本地实现，模型语境投影现在也记录实际展示覆盖。10月16日 l4 真实切片再次因模型端点网络错误未形成可评价样本，不能据此评价新方法；无模型本地 l4 切片完成5/5 Add、1/1 Search，top-5召回与闭合链均为1.0，只证明确定性装箱和观测接线。64项当前 amlink/benchmark 回归通过。跨数据集锚点和定向复验见[10月13日扩展验证](./doing/2026-10-13-amlink-expanded-validation.md)。历史完整基线Add 68/145、Search 99/100及旧0.2.0审计分别见[100题诊断](./doing/2026-10-11-amlink-100-rerun-analysis.md)和[核心审计](./doing/2026-10-11-amlink-core-audit.md)。

新增的 Mem0/AM-Link 同条件 Add/Search/Answer 运行见[10月14日真实模型链路补充实验](./doing/2026-10-14-real-model-chain-report.md)：关系组和拒答小例已完成端到端回答，B03 长历史暴露 Add/Reflection 丢批，PersonaMem 暴露失败 Add 仍留下部分可检索状态，C02 暴露 Answer 越过条件证据。分享页[docs/report](./report/README.md)已同步这些案例观察。

`private/` 仅本机存在：包含已授权保存的 SSH 账号、服务器环境快照和模型 Key。公开文档只记录接入方法。

服务器当前保留通用公网基础设施和示例：`https://121.43.49.84/hello`、`https://121.43.49.84/health`，HTTP 也可访问。使用 Let’s Encrypt shortlived 生产 IP 证书及自动续期；它们不属于 AM-Link API。维护方式见[服务器接入经验](./operations/server.md)，服务器上的可读说明位于 `/opt/public-web/README.md`。

一期原始长文从 [归档设计理念](../archive/phase-1/设计理念.md) 和 [历史文档索引](../archive/phase-1/docs/README.md) 查阅。它们保留原貌；尚未完成的旧计划不会自动成为二期任务。
