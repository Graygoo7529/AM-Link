# 进行中的工作

| 日期 | 计划 | 当前状态 |
| --- | --- | --- |
| 2026-10-23 | [Reflection闭环实施与复验](./2026-10-23-reflection-convergence-implementation.md) | 工程实施done；140项回归、220次真实调用；构图/探索未验收，默认确定性装箱，未扩大20/100题 |
| 2026-10-23 | [提交后闭环复核](./2026-10-23-reflection-convergence-audit.md) | done：126项复核、8次轨迹重析、3个本地反例、6次真实诊断；部分工程验收重新打开，改进收益待验证 |
| 2026-10-23 | [Reflection闭环执行方案](../phase-2/reflection-convergence-plan.md) | 已按确认方案实施并核对；机制真实覆盖部分完成，方法质量验收保持开放 |
| 2026-10-23 | [P0/P1实施核对](./2026-10-23-evidence-loop-implementation.md) | 五包已接入；工程回归、真实L04/BEAM切片与失败定位；方法质量继续验收 |
| 2026-10-23 | [P0/P1执行方案](../phase-2/evidence-loop-execution-plan.md) | 保留完整目标、接口、预算、水位和验收条件；实际状态见实施核对 |
| 2026-10-23 | [当前实施与设计缺口核查](./2026-10-23-design-status-audit.md) | done：核查afe8c8d、100项回归；离线复现引用位置错位、同源片段遗漏及图证据装箱丢失；新问题待修复，真实质量未验收 |
| 2026-10-23 | [提交前检查与测试产物隔离](./2026-10-23-commit-readiness.md) | done：隔离默认测试产物，修复装箱/覆盖/探索门槛边界；代码已在afe8c8d提交，历史测试产物清理仍待处理 |
| 2026-10-15 | [证据链修复](./2026-10-15-evidence-chain-repair.md) | 已实现并持续校准：Reference片段、Reflection探索门槛、来源覆盖；真实模型复验尚未完成 |
| 2026-10-14 | [100题重跑复核](./2026-10-14-amlink-100-rerun-review.md) | done：完整报告生成；128/145 Add、100/100 Search；Search BFS 已实测，Reflection 仍未实测出 Inspect/Backlink，证据闭合和图质量继续改进 |
| 2026-10-13 | [跨数据集扩展真实链路验证](./2026-10-13-amlink-expanded-validation.md) | done：21 个跨数据集锚点、3 个定向复验；Reflection 图探索与证据链质量仍未验收 |
| 2026-10-11 | [0.2.1核心修复与方法议题](./2026-10-11-amlink-core-repairs.md) | done：工程修复、52项回归、积压复放和真实小切片；整理触发、语义图与证据覆盖继续设计 |
| 2026-10-11 | [0.2.0核心审计](./2026-10-11-amlink-core-audit.md) | done：源码/数据库/轨迹复核与无网络复现；作为0.2.0失败基线；后续工程修复见同日0.2.1报告 |
| 2026-10-11 | [0.2.0重构实施与回归](./2026-10-11-amlink-refactor-implementation.md) | 部分实现；原完成性结论已按同日审计订正 |
| 2026-10-04 | [数据集与靶场主计划](./2026-10-04-dataset-benchmark-plan.md) | 数据基础与本地环境已实现；数据扩充、真实目标对照继续跟踪 |
| 2026-10-05 | [数据层解耦、公开数据获取与核验](./2026-10-05-dataset-decoupling.md) | done：中立 pack、双向适配、7 种来源的完整文件或小样本、5 份环境计划和本地 HTTP 管线核验；缺失材料明确记录 |
| 2026-10-05 | [案例库与数据扩充](./2026-10-05-case-study-expansion.md) | done：八个案例、PerLTQA 中文双文件与读取器、CL Life/BEAM 新样本及离线 plan；新增候选和下载限制已记录 |
| 2026-10-05 | [案例库迁移与可复用展示](./2026-10-05-case-library-viewer.md) | done：根目录 casestudies、同源网页/会话视图、手动下载入口；不维护页面选择进度 |
| 2026-10-05 | [统一可视化与观测接口](./2026-10-05-research-visualization.md) | done：四视角、来源样本与 API trace、版本化内部观测接口；实际二期埋点和方法实验待做 |
| 2026-10-07 | [Hugging Face 数据重试与核验](./2026-10-07-huggingface-retry.md) | done：LongMemEval、CL-bench、BEAM、MemoryAgentBench、PersonaMem-v2/v3 缺口取得或核验；大包按范围暂不全量转 pack |
| 2026-10-07 | [全量数据研究与记忆案例](./2026-10-07-dataset-research.md) | done：全量结构、6 个研究包、26 个案例、BM25 与 Mem0 六条件实测、五视角展示 |
| 2026-10-07 | [研究基础设施闭环](./2026-10-07-research-infrastructure.md) | done：26 个案例、切片运行、标准产物、持久评注、四视角联动与设计检查合并 |
| 2026-10-08 | [Add/Search 记忆研究调研综述](./2026-10-08-memory-research-survey.md) | done：跨数据集难点归纳、6 个 Mem0 切片、BEAM 冲突重跑与 AM-Link 设计建议 |
| 2026-10-08 | [AM-Link 二期方法实现](./2026-10-08-amlink-implementation.md) | done：本地 0.1.0、严格 Add/Search、引用图、native 观测、91 项测试与有限真实切片；效果校准继续，未部署 |
| 2026-10-08 | [AM-Link Answer 靶场与真实案例复核](./2026-10-08-amlink-answer-research.md) | done：诊断 Answer 接入标准观测，7 个新增 Add/Search 切片、8 个真实 Answer、人工后验核对；reflection 结构错误仍阻断四类案例 |

各计划只使用允许获取的公开来源。实施产物、数据许可与限制以各计划和数据目录说明为准。
