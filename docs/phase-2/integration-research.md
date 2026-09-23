# 二期接入调研

核验日期：**2026-09-23**，本轮重新读取官网文档、API Guide 和官方公开评测仓库。以下是二期调研输入，不代表已经完成二期接入；正式绑定前仍以主办方冻结的 contract 和申请页为准。

## 已确认的变化

| 项目 | 当前官方说明 | 对我们的影响 |
| --- | --- | --- |
| 时间 | 9 月 20 日开始；10 月 31 日 23:59 材料截止；11 月 4 日 23:59 评测停止，均为 UTC+8 | 提前留出 Smoke、修复和 Full 时间 |
| 接入 | 开源方法榜与商业产品榜均自行托管 Add/Search；源码或 Docker 不能替代在线接口 | 延续自托管，但重新部署二期版本 |
| 赛道 | 文本含 Streaming 持续记忆；另有代码、多模态 | 优先研究文本增量写入，其他赛道需单独决定 |
| 配额 | Smoke 每小时 1 次，每赛道本期最多 30 次；每 Key/赛道最多 2 次 Full，第二次在首次完成 30 天后解锁 | 不能把官方 Full 当作快速调参循环 |

来源：[用户文档](https://agentmemories.ai/zh-cn/docs)、[参赛说明](https://agentmemories.ai/rules)。正式受理后固定参评版本；一期的成功评测不等于二期版本已经绑定或审核通过。

## 二期模型约束

当前官方公开信息应分成平台侧和参赛方侧：

| 范围 | 当前规则 | 对我们的结论 |
| --- | --- | --- |
| Answer / Eval | 平台锁定 Answer 模型、提示词、评测器和聚合流程；参赛方不能选择 | Add/Search 只需返回证据，不实现回答或评分 |
| 开源方法榜 Add | Full 检查项明确写明应使用 `gpt-4o-mini` | 二期 Add 中所有生成式 LLM 调用暂固定为 `gpt-4o-mini`，兼容代理可以更换，但模型标识不能改成其他模型 |
| 开源方法榜 Search | 当前公开页面没有单独列出 Search 的模型白名单；旧申请页曾显示 Add/Search 均为 `gpt-4o-mini` | 为避免边界争议，Search 也暂固定 `gpt-4o-mini`；正式提交前向主办方确认是否允许其他 Search 模型或无 LLM Search |
| Embedding / 索引 | 官方文档明确不规定数据库、索引或 embedding 模型 | 可以使用本地或任意合规 embedding，也可以走词法/规则检索；需披露模型、版本、维度和费用 |
| 商业产品榜 | 当前 Full 检查项写明 Add/Search 没有模型限制 | 不适用于我们的开源方法榜 |

因此当前最稳妥的开源配置是：Add `gpt-4o-mini`，Search `gpt-4o-mini`（或确定性检索但先取得主办方确认），embedding 采用可替换的本地/外部模型。官方只比较我们提供的 Add/Search 证据，统一 Answer/Eval 不应被我们的实现替代。来源：[官方 Full 检查项](https://agentmemories.ai/zh-cn/docs)、[公开评测仓库说明](https://github.com/AML-memory/agent-memory-leaderboard)。

## Add/Search 边界

文本接口外壳基本沿用一期：Add 接收 `request_id/messages/user_id/session_id`，成功返回 `success=true` 和原样三个 ID；Search 接收 `query/user_id/top_k`、可选顶层 `options`，返回按相关性排序的 `data`，其中 `id/content` 必需。原文写入后立即可检索，Search 只返回证据；正式 `top_k=100`，超过数量会报协议错误。

普通文本分块以 20 条消息或 2,000 个 Adapter 计数的词为边界；Streaming 按增量单元写入，同一问题可能在不同记忆阶段重复检索。单次 Add/Search 最长 30 分钟。同步为默认；202 仅适用于已经审核绑定状态查询地址的版本。

正式接口使用 Token、Bearer 或 X-Api-Key，健康检查无需鉴权；`none` 只适用于公开 Smoke。来源：[用户文档接口章节](https://agentmemories.ai/zh-cn/docs)。

多模态将文本字段扩展为有序文本/图片数组，图片为内联 Base64，不能用远程图片 URL；每张解码后最多 10 MiB，每次 Add 或 Search 响应的图片合计最多 30 MiB。旧字符串模型及 Nginx 4 MiB 限制不能直接支持它。来源：[API 指南](https://agentmemories.ai/api-guide)。

接口没有统一字符截断上限，不支持的请求要显式报错。Answer 有独立上下文预算，超出时按候选返回顺序取前缀，因此排序及单条证据长度会影响真正进入回答的内容；不能依赖平台替我们重排。30 分钟是官方请求上限，不是本机必须等待的时长，应用与网关应采用一致的、更小且经实测的截止预算。

## 错误与重试：二期应直接利用官方机制

| 场景 | 官方处理 | 我们的设计选择 |
| --- | --- | --- |
| 网络错误，408/425/429/500/502/503/504 | Add/Search 有界退避重试 | 返回真实暂时失败，默认不做内部重试与后台补偿 |
| Add 409、524 | Add 也会重试，单逻辑写入最多 32 次请求尝试 | 相同 ID/内容保留幂等；409 不代表成功 |
| Search 409，其他永久性 4xx | 不重试 | 参数、权限问题应明确返回 400/401/403/422 等 |
| 429 | 遵循有效 Retry-After，最多等待 60 秒；未给出时等 60 秒 | 返回容量不足及合理等待信息，不把请求无限排队 |
| 200 但返回结构错误 | 当前阶段失败 | 在返回成功前校验完整协议 |

来源：[API 指南 Runtime Rules](https://agentmemories.ai/api-guide)。这些约定足以支持请求失败后由官方重新投递，没有必要复制一期的后台任务系统。

建议把“同 ID、不同内容”的永久错误映射到明确 400/422；只把可恢复的写入处理中状态用于 409，避免无意义地触发官方 32 次尝试。必要索引未完成时不能缓存成功；重试只推进未完成工作。可选降级路径必须提前定义，不能在故障时悄悄改变方法。

## 官方基准套件与可用开源数据

官网当前展示的文本基准卡为：

| 赛道 | AML 名称 | 主要内容 | 是否适合立即做本地 Add/Search 检验 |
| --- | --- | --- | --- |
| 文本 | LoCoMo-Refined | 多会话、长程对话记忆 | **最适合**；先用我们已有 LoCoMo 小样本和原始仓库做回归 |
| 文本 | ScriptMem | 脚本化事件、关系、选择、排序和时间演化问题 | 适合分析问题类型；原始剧本正文不随仓库发布，完整 Add 重放受限 |
| 文本 | LongMemEval-Refined | 长上下文记忆问答，适配平台写入/检索流程 | 适合小规模；先使用公开 LongMemEval-S 数据，不把原始仓库等同于 AML refined bundle |
| 文本 | LongMemEval-S | 长程证据问答、知识更新、时间推理、跨会话和 abstention | **优先**；公开仓库包含 500 个问题，可抽取小切片 |
| 文本 | CLBench | 上下文学习、规则/流程和专业领域知识 | 适合后续；任务与 rubric 较复杂，先解析格式再运行 |
| 文本 | PersonaMem-v2 | 隐式用户画像、偏好和长上下文个性化 | 适合检验个性化与更新；数据规模较大，先抽样 |
| 文本 | BEAM | 128K/500K/1M/10M 多尺度长对话和长期记忆问题 | 后续压力测试；存储、切分和运行成本最高 |
| 多模态 | ATM-Bench | 图文记忆，关注问题质量 | 只有选择多模态赛道时再实现 |
| 多模态 | Mem-Gallery | 图集式记忆检索，F1 评估 | 只有选择多模态赛道时再实现 |
| 代码 | CAMBench Coding | 150 个软件工程任务，relevant/noisy 共 300 次 | 当前代码赛道正式计分套件，但任务不是公开文本记忆数据 |
| 代码 | SWEContextBench | 代码记忆参考目录 | 当前不作为 AML 代码赛道正式计分基准 |

官方公开仓库说明文本套件覆盖 PersonaMem、LoCoMo-Refined、CLBench、BEAM、LongMemEval、ScriptMem，并公开每个基准的配置/contract 目录；语料、held-out 问题、金标和私有标注不在仓库中。机器 contract 快照 `textual-contract-2026-09-23.json` 仍使用较粗的 ID：`scriptmem`、`locomo`、`longmemeval`、`clbench`、`beam`、`personamem_v1`、`personamem_v2`。因此不能把旧 ID 或原始公开数据直接当作官方二期 bundle。

可先分析的公开来源：

- [LoCoMo 原始仓库](https://github.com/snap-research/locomo)：10 个长期对话，平均约 300 turns/9K tokens，最多约 35 sessions；仓库提供 `locomo10.json`，但不提供原始图片文件。
- [ScriptMem](https://github.com/memorax-ai/ScriptMem)：457 个问题、4 部脚本作品、6 类问题；仓库提供任务问题和答案格式，但出于版权原因不包含原始剧本正文。
- [LongMemEval](https://github.com/xiaowu0162/LongMemEval)：公开 `longmemeval_s/m/oracle`，每个文件 500 个实例，覆盖单会话、跨会话、偏好、时间推理、知识更新和 abstention。
- [PersonaMem-v2](https://github.com/bowen-upenn/PersonaMem-v2)：约 1,000 个 persona、20,000+ 偏好、300+ 场景，重点是对话中隐式出现的偏好；适合检验个性化记忆和更新。
- [BEAM](https://github.com/mohammadtavakoli78/BEAM)：100 个对话、约 2,000 个验证问题，覆盖 128K 到 10M token 多尺度上下文；适合后续长上下文压力测试。
- [CL-bench](https://www.clbench.com/)：专业领域上下文学习、规则和复杂流程任务；先阅读任务格式和 rubric，再决定下载和切片方式。

这些来源的公开数据只用于本地方法分析，不能用于重建 AML 私有评测集、训练/微调模型或提交答案。官方要求评测数据及派生副本在任务完成后按规定删除；运行记录应只保留必要的脱敏统计。

## 公开机器协议与边界

本次直接读取了官网使用的[文本赛道 contract](https://agentmemories.ai/api/v1/evaluation-tracks/textual/contract)，快照见 [textual-contract-2026-09-23.json](./sources/textual-contract-2026-09-23.json)：

- 协议标识：`textual-v1`、`ldbd-textual-official-suite-v1`；记忆接口为 `memory-api-v1.1`。
- Add 并发可选 16–64；Search 并发可选 16–256。它们是调度上限，不是保证吞吐；一期无模型压测不等于真实模型容量。
- contract 数据项包括 `scriptmem`、`locomo`、`longmemeval`、`clbench`、`beam`、`personamem_v1/v2`；官网当前把其中部分拆成 `LoCoMo-Refined`、`LongMemEval-Refined` 和 `LongMemEval-S`。完整官方 bundle、金标和题量可能随版本冻结变化，不能仅凭名称推断实际文件或样本数。
- contract 还描述 `/v1/runs` 等评测 Adapter 接口，那是平台编排层的协议；参赛记忆系统仍只需提交 Add/Search 与必要健康地址，不要误实现整套评测平台。

API 文档提到 Streaming，但此公开数据项列表没有单独名为 Streaming 的项；不能据此断言它不参与评测，需在正式绑定前核对冻结版本和任务调度。

## 仍待正式绑定前核验

官网当前 Full 检查项对开源方法榜明确写的是 Add 使用 `gpt-4o-mini`；Search 是否必须同一模型、无 LLM Search 是否允许、embedding 是否需要在申请表单声明，公开文档没有完全展开。暂按 Add/Search 均固定 `gpt-4o-mini` 设计，正式绑定前再次查看申请页冻结版本并向主办方确认。商业榜的宽松约定不能套用到开源榜。

当前配额、数据包和模型文案可能继续更新。实施前再次核验官网与选中版本；一期保存的旧运行说明仅作为经验。官方评测内容及派生副本仅用于对应任务，并在完成后 30 天内删除。来源：[用户文档数据条款](https://agentmemories.ai/zh-cn/docs)。

## 下一步执行顺序

| 状态 | 事项 | 验收依据 |
| --- | --- | --- |
| done | 一期代码归档、设计/工程经验整理、二期文档与公开 contract 核验 | 根文档及归档记录 |
| todo | 确定二期赛道，核实模型差异、版本绑定、容量和数据规则 | 记录明确来源与核验日期 |
| todo | 新目录建立最小同步 Add/Search，优先移植必要协议和存储能力 | 成功即持久化可检索；幂等、隔离、严格错误结构 |
| todo | 移除后台补偿，设计失败重投、deadline、限流及费用观测 | 停流后没有新增模型调用；官方式重复投递可恢复 |
| todo | 从公开对话与自造增量案例验证记忆机制 | 固定切片；分别测召回、证据链、更新/遗忘、空结果与费用 |
| todo | 扩大真实 provider 的质量与故障实验 | 新库与缓存分开报告；同切片对照；有明确调用预算 |
| todo | 部署独立二期版本，绑定 Key，Smoke 后 Full | 本地协议/容量/停流检查通过，固定 commit 和模型配置 |

本轮不启动新模型实验，也不重新上线归档服务。先完成规则与最小失败语义，再根据可重复的收益增加记忆机制。
