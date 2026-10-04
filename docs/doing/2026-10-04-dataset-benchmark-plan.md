# 数据集目录与本地 Add/Search 靶场

日期：2026-10-04；状态：`in_progress`。

## 目标

1. 从各 benchmark 作者/维护方发布源核实比赛提到的公开数据集：下载入口、原始文件、版本、许可、切分/读取/评测办法，并与 AML 卡片名称分开映射。
2. 创建 `dataset/`，按来源组织可获得原始数据、忽略大型/许可受限的数据文件，并提供可复现的 inspect、split、prepare 和使用说明。
3. 创建 `benchmark/`，将官方参赛者 Add/Search contract 本地化，让二期 AM-Link 和 Mem0 的已发布 Python 包或 OSS REST 服务可以使用同一 manifest 和选样本比较。
4. 因正式平台只有一次评测机会，让靶场可以用小切片反复验证 Add/Search，并保留原始请求、响应、样本证据、rank 和错误，支持定位具体失败样本及可观察阶段。

## 设计边界

- 官方负责 Answer/Eval；公开上游数据与靶场的证据召回指标是本地诊断，不伪装成 AML 冻结题包、官方 judge 或 leaderboard 分数。
- 每个 dataset source 记录维护方 URL、revision、SHA（可得时）、许可、split、原始格式、处理规则和评估契约。作者原版、第三方 refined 发布、AML 同名卡必须区分。
- 数据、manifest 和 trace 均可能含可还原对话，保存在 Git 忽略的 `dataset/data/`。不将数据发送到外部模型/API，除非操作者主动选择目标服务。
- Target 统一遵循官方 `/v1/memory/add` 和 `/v1/memory/search` 语义；Mem0 可通过其已发布 Python 包或 OSS REST API 接入，不复制/构建 Mem0 源码，不运行 Docker。Python 包由操作者显式安装，靶场不触发模型请求。
- Run 固定 manifest 与顺序，给每次运行新的 user/request/session namespace，不做靶场自动重试。真实 provider usage/费用未知就写 `null`。
- 对失败的归因只覆盖接口边界的证据：Add 失败、Search 失败、source turn 字面未匹配、命中排名低。若目标内部日志不可观测，不推断私有阶段/内部原因。

## 子计划和验收

| 状态 | 计划 | 验收 |
| --- | --- | --- |
| done | [上游数据源调研](./2026-10-04-dataset-research.md) | 核对作者/维护方源、许可、体量、processor/evaluator 及 AML 名称关系；区分脚本版权缺口和未公开 bundle |
| in_progress | [数据集目录与读取器](./2026-10-04-dataset-preparation.md) | 可用原始数据与切片可复现；其余可获取源有许可、format、split、reader、评测计划；网络恢复时取得 LongMemEval-S 并校验 |
| done | [Add/Search 靶场](./2026-10-04-benchmark-arena.md) | 同一 manifest 可运行不同 target；逐请求 trace 和按 case/search inspect 可追到具体 source Add 与 evidence；离线测试通过 |

## 执行记录

| 日期 | 工作 | 结果 |
| --- | --- | --- |
| 2026-10-04 | 读取项目记忆、一期接口经验、二期调研、AML/Mem0 公开接口资料 | 确认比赛参赛方只供 Add/Search；官方负责 Answer/Eval |
| 2026-10-04 | 调研数据源 | 核查 SNAP LoCoMo、LoCoMo-Refined community candidate、LongMemEval S/M/Oracle、ScriptMem、CL-bench/Life、PersonaMem-v2 和 BEAM/10M 作者发布；写明许可和回放适用性 |
| 2026-10-04 | 数据目录第一版 | 已有 SNAP LoCoMo 原文和固定小 manifest；LongMemEval-S downloader/reader 已实现，pinned 下载返回 HTTP 502 且未留下残片 |
| 2026-10-04 | 靶场第一版 | 实现 AML API 和 Mem0 OSS REST target、隔离 namespace、顺序 replay、JSON report 和 JSONL trace |
| 2026-10-04 | 按用户补充意图修订设计 | 证据 target 关联源 turn/session 与对应 Add request；增加 source Add 失败/字面未命中/低 rank/Search 错误诊断和单样本 inspect 入口 |
| 2026-10-04 | 增加 Mem0 开箱适配 | 增加对已发布 `mem0ai` Python package 的 Add/Search adapter；不下载源码、不自动安装、不调用模型。官方 Python quickstart 确认 `Memory.add`/`Memory.search` 用法，REST 自托管说明以 Docker Compose 为常见路径 |
| 2026-10-04 | 离线复核和重新获取数据 | dataset 4 项、benchmark 测试及 CLI/compileall 复核见下方最新状态；LoCoMo source mapping 8/8 对应到 Add request。LongMemEval-S pinned 下载返回 HTTP 502，`.partial` 已清理 |

## 当前验证与待办

- [x] 根目录和 docs 索引链接 `dataset/`、`benchmark/` 和此计划。
- [x] 官方公开名称不是原始数据源的 crosswalk 已记录；不存在公开证据的 AML 私有包不尝试复原。
- [x] 数据清单能分出已接入读取器和尚未接入的公开数据源，并记录 source/许可/split/use。
- [x] LoCoMo 和 LongMemEval 的 evidence 映射加入原始来源 ID、会话/turn 位置与 Add request ID。
- [x] inspect 命令输出所选样本的 report query、相关 Add event 与 Search event。
- [x] 运行 dataset 4 项、benchmark 9 项单元测试、`compileall` 和 CLI help；inspect 对 source Add 失败的关联由离线测试验证。
- [ ] 运行 `git diff --check` 与 `git status --short`；检查 raw data、run trace、凭据、数据库和临时文件仍被忽略。
- [ ] 可运行服务上线后才做 AM-Link/Mem0 端到端目标比较；当前不因文档任务启动模型、连接云服务或产生费用。

## 完成标准与限制

对已取得且已接入的公开小切片，可从 report query 回到 JSONL Search 请求/候选，再回到对应 source Add request，并查看 HTTP/contract 错误、证据命中 rank。公开数据诊断闭环不依赖官方唯一一次评测。

仍不能回答的原因包括：target 内部摘要为何丢字段、上游模型实际调用/费用、未暴露的向量/记忆内部状态、答案级正确性。需要被测服务提供可关联且不泄密的内部 trace，或显式增加有预算的 Answer/Eval adapter，才可继续归因。这些都不得由 HTTP 200 或证据字面匹配臆断。
