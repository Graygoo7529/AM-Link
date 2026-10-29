# 项目文档

2026-10-29当前：[100题准备实施与核对](./doing/2026-10-29-hundred-question-readiness-implementation.md)、[执行计划](./phase-2/2026-10-29-hundred-question-readiness-plan.md)、[真实台账](./doing/2026-10-29-hundred-question-readiness-run-ledger.md)。工程及六类分版本预检完成，356回归＋3子测试；最终r11完整PersonaMem13/13 Add、6/6 Search。26记录/100题/780 Add已冻结，同版剩94题未运行；质量/正式参赛未验收。以下为历史阶段。

2026-10-29最新复核：[扩大本地测试前的现状与数据预检](./doing/2026-10-29-broad-test-readiness-audit.md)。310回归＋3子测试复验通过；仍有关系阻塞独立节点、变化/归属混淆及长episode嵌入边界问题。已离线核对12个准备包，提出6类数据/26记录/100题完整历史诊断范围；未启动真实大批量或修改方法。

2026-10-29最新交付：[可见增量与检索实施核对](./doing/2026-10-29-visible-increment-implementation.md)、[16份真实档案台账](./doing/2026-10-29-visible-increment-run-ledger.md)、[执行计划](./phase-2/2026-10-29-visible-increment-execution-plan.md)。四项工程改进done，310回归＋3子测试；803次尝试/791响应。旧字段和新增支持、Select与人工图组件有收益；最后新库4/6整理组、零边，自动图与完整历史未验收。以下“仅建议”为实施前历史。

最新复核：[10月29日明显改进点](./doing/2026-10-29-next-improvements-audit.md)：旧节点时间字段未进入自然叙事却要求精确复用；补来源审查混淆“旧事实成立”与“新增原文支持”；导航身份与Search分环节验证仍需改进。本轮只有离线核对和建议，无方法改动或新模型调用。

最新实施：[来源约束、叙事归属与增量整理](./doing/2026-10-28-grounded-increment-implementation.md)、[真实台账](./doing/2026-10-28-grounded-increment-run-ledger.md)、[执行计划](./phase-2/2026-10-28-grounded-increment-plan.md)。四项改进入默认流程；299回归＋3子测试；关系定义体积、真实归属和复用效果分别核查，不将 API 成功等同于图质量通过。

当前实施：[工具协议与局部整理修订](./doing/2026-10-28-tool-repair-implementation.md)、[运行台账](./doing/2026-10-28-tool-repair-run-ledger.md)、[执行计划](./phase-2/2026-10-28-tool-contract-and-reflection-repair-plan.md)。已实施统一工具校验、逐项内容修订与依赖检查点；286回归＋3子测试。工具往返16场景对照未达到门槛，未加入生产。真实协议/语义及完整历史验收仍须按报告分别判断。

最新分析：[整理困难与模型接口核查](./doing/2026-10-28-reflection-api-audit.md)。已提交基线 `b000d96`；离线重验 145 份输出并做 6 次合成接口探测，发现严格工具约束的代理差异、schema 以外的字段歧义及审查异常的修订断点。不是本次请求时间不足；只有诊断与改进建议，未改默认方法。

当前交付：[节点保真与简明审查实施核对](./doing/2026-10-28-memory-integrity-implementation.md)、[执行计划](./phase-2/2026-10-28-memory-integrity-review-plan.md)。旧节点保护、当前支持来源、最终正文审查及语气/时间检查已默认实施；258 项回归＋3 子测试，236 次真实调用。最终三切片 8/8 Add、3/3 Search，来源齐全，但 LM04 仅 1/3 整理组完成，三库零边，整体质量未验收。下方只有分析是实施前阶段。

更新日期：2026-10-28。目标是让新会话快速恢复项目背景和决策依据；旧过程记录留在一期归档中。

最新离线审读：[切实可行的改进点](./doing/2026-10-28-practical-improvement-audit.md)。在已提交 `ff706cb` 的真实轨迹中确认派生 episode 换题覆盖、审查来源被提交时重新并回，以及 review 错嵌层级；建议先稳定记忆内容与简化审查协议。只有分析，未改方法或新增模型调用。

模型迁移：[v4 / 1024 实施核对](./doing/2026-10-28-embedding-v4-migration.md)、[执行与长文本设计](./phase-2/2026-10-28-embedding-v4-migration-plan.md)。默认智增增 v4 / 1024 维 / 批量 10 已生效，旧库/缓存 1651 文件备份清理；231 项回归＋3 子测试，新库 6/6 Add、2/2 Search。长文本完成 4 次真实探测，多片段索引尚未实施；整体图质量未验收。此前[规则核验](./doing/2026-10-28-embedding-v4-verification.md)保留为迁移前记录。

最新入口：[Add/Search 交付边界实施与核对](./doing/2026-10-27-delivery-contract-implementation.md)、[执行计划](./phase-2/2026-10-27-add-search-contract-and-convergence-plan.md)。Add 原子接收、Search 单步合入、逐组恢复/局部修订、预算范围传播及网页状态已实施。224 项回归与 3 子测试通过；6 个新库档案加组件共 618 次真实模型调用，41/41 Add、21/21 Search。整理与图语义仍未验收；仅两份不同完整历史，未扩大 12 份/36 问，无部署。

实施前问题复核见[Add 失败与改进讨论](./doing/2026-10-27-add-failure-review.md)：基线已提交为 `ee6fe76`；最终三次失败均阻塞在同一未完成组，审查返回后尚无继续局部修订路径，其中两次还有重复条目编号。本次仅离线分析和文档，后续建议尚未实施。

此前阶段见[方法收敛实施与核对](./doing/2026-10-27-convergence-implementation.md)、[执行清单](./phase-2/2026-10-27-convergence-execution.md)和根DESIGN。原文段分组、程序推进、联合审查、精确向量复用已进入唯一默认方法。198项回归、3子测试通过；578次模型尝试中563次有返回。工程与真实质量分开：完整讨论末轮Add1/4，图语义未验收；未部署。

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

此前同日阶段：[单一主链路实施与实测](./doing/2026-10-26-live-method-implementation.md)、[执行计划](./phase-2/2026-10-26-live-method-plan.md)和根DESIGN。分步Reflection、来源对应/局部校正及原文卡Select直接进入默认方法；取消双路径开关。真实成功、变体失败与完整人物记录分栏。前一包[证据窗口报告](./doing/2026-10-26-evidence-and-draft-implementation.md)是历史基线，不能继续沿用其默认关闭结论。

此前阶段：2026-10-23 先读[闭环实施与真实复验](./doing/2026-10-23-reflection-convergence-implementation.md)及[执行计划核对](./phase-2/reflection-convergence-plan.md)：140项回归通过，新增220次真实调用。统一可见范围、目标正文保留、关系阻断反馈、缓冲误触发修复已实施；真实Select/查询扩展在历史图副本上执行，但当前构图仍不稳定、整体方法未验收。LLM装箱合法但来源覆盖6/7，确定性为7/7，维持默认。未扩大20/100题、未部署。[之前的复核](./doing/2026-10-23-reflection-convergence-audit.md)与[前轮实施核对](./doing/2026-10-23-evidence-loop-implementation.md)保留为过程记录；8项旧跟踪测试产物仍待处理。

历史验证见[10月14日100题重跑复核](./doing/2026-10-14-amlink-100-rerun-review.md)和[10月15日证据链修复记录](./doing/2026-10-15-evidence-chain-repair.md)：完整修复版为128/145 Add、100/100 Search；目标Add均成功的94道题上，top-5证据召回约55.3%、完整链约59.6%。Search实测338次Inspect、72次Backlink和787次Select；新的 Reference 互补片段、证据闭合和 Reflection 先看再写门槛已完成本地实现，模型语境投影现在也记录实际展示覆盖。10月16日 l4 真实切片再次因模型端点网络错误未形成可评价样本，不能据此评价新方法；无模型本地 l4 切片完成5/5 Add、1/1 Search，top-5召回与闭合链均为1.0，只证明确定性装箱和观测接线。64项当前 amlink/benchmark 回归通过。跨数据集锚点和定向复验见[10月13日扩展验证](./doing/2026-10-13-amlink-expanded-validation.md)。历史完整基线Add 68/145、Search 99/100及旧0.2.0审计分别见[100题诊断](./doing/2026-10-11-amlink-100-rerun-analysis.md)和[核心审计](./doing/2026-10-11-amlink-core-audit.md)。

新增的 Mem0/AM-Link 同条件 Add/Search/Answer 运行见[10月14日真实模型链路补充实验](./doing/2026-10-14-real-model-chain-report.md)：关系组和拒答小例已完成端到端回答，B03 长历史暴露 Add/Reflection 丢批，PersonaMem 暴露失败 Add 仍留下部分可检索状态，C02 暴露 Answer 越过条件证据。分享页[docs/report](./report/README.md)已同步这些案例观察。

`private/` 仅本机存在：包含已授权保存的 SSH 账号、服务器环境快照和模型 Key。公开文档只记录接入方法。

服务器当前保留通用公网基础设施和示例：`https://121.43.49.84/hello`、`https://121.43.49.84/health`，HTTP 也可访问。使用 Let’s Encrypt shortlived 生产 IP 证书及自动续期；它们不属于 AM-Link API。维护方式见[服务器接入经验](./operations/server.md)，服务器上的可读说明位于 `/opt/public-web/README.md`。

一期原始长文从 [归档设计理念](../archive/phase-1/设计理念.md) 和 [历史文档索引](../archive/phase-1/docs/README.md) 查阅。它们保留原貌；尚未完成的旧计划不会自动成为二期任务。
