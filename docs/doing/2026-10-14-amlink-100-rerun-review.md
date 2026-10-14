# 2026-10-14 AM-Link 100题重跑复核

日期：2026-10-14。运行：`amlink-repaired-locomo-100-real-20261013n`。本报告记录完整报告生成后的事实、与旧完整基线的可比指标，以及下一步方法判断。它不把一次随机模型运行当作确定性消融，也不把 HTTP 成功率当作答案准确率。

## 结果先看

| 指标 | 旧完整基线 `20261012k` | 本次修复版 `20261013n` | 判断 |
| --- | ---: | ---: | --- |
| Add | 68/145 | 128/145 | 工程完成率明显提高，但仍有17次未成功 |
| Search | 99/100 | 100/100 | Search 外壳稳定 |
| 全体 top-5 证据召回 | 62.8% | 56.1% | 本次没有证明方法质量提升 |
| 全体 top-5 完整链 | 63.0% | 59.0% | 多证据问题仍有缺口 |
| 目标 Add 均成功的题目 | 54题/75目标 | 94题/152目标 | 可评价样本明显增加 |
| 该子集 top-5 证据召回 | 76.0% | 55.3% | 结构写入增加后，检索质量仍受噪声和模型路径影响 |
| 该子集 top-5 完整链 | 72.2% | 59.6% | 不能只用 Add 成功率判断改进 |
| Add p95 | 82.1秒 | 89.9秒 | 仍在单次30分钟上限内，但长尾增加 |
| Search p95 | 74.0秒 | 83.4秒 | BFS/Select 成本有长尾 |

旧基线与本次运行使用相同的145 Add、100 Search问题和164个证据目标；模型输出具有随机性，所以上表是运行对照，不是严格的代码消融实验。

## Add 发生了什么

本次17个失败按错误码分布为：

- `forget_requires_explicit_new_user_instruction`：6次。模型提出了没有当前用户明确授权的遗忘操作，系统正确拒绝；代价是这些 Add 没有进入成功集合。
- `mutation_duplicate_ref`：4次。模型在同一 mutation 中重复使用引用，说明结构化 tool call 仍需要更稳定的去重提示或局部清洗边界。
- `mutation_fact_overwrite`：3次。模型尝试覆盖已有事实，暴露更新/冲突语义没有被稳定区分。
- `mutation_schema_invalid`：3次。仍有结构化输出不满足当前 schema。
- `model_tool_output_invalid`：1次。模型工具输出无法解析。

这些失败都返回了显式错误，没有伪装成成功，也没有内部重试。最低 episode 和前缀提交是否保留，以对应请求轨迹为准；不能把失败 Add 的内容当作已完成 Reflection。

本次数据库最终为：`153 episode`、`216 event`、`96 fact`、`2 person`；关系为 `61 about`、`53 contains`、`7 same_event_as`、`6 supersedes`。相对旧基线，派生 event/fact 更多，但 `contains` 边更少。这不是图质量提升的充分条件：节点主体、来源支持和关系语义仍需逐项核对。

## Search 真实路径

本次 Search 的观测记录了：

- `227` 次 Query 合并和结果阶段；
- `787` 次 Select；
- `338` 次 Inspect；
- `72` 次 Backlink；
- `412` 次 BFS action，其中 `inspect=338`、`backlinks=72`、`stop=2`；
- `100` 次最终证据装箱。

这证明标准 Search 已经不是单次 BM25 命中，而是“Query → Select → Inspect/Backlink → Context 更新 → 继续探索或停止 → 装箱”的真实链路。装箱样例中，单个 episode 可以展开其全部来源消息，并记录来源角色、顺序和 UTC 时间；因此旧的“大块正文重复导致只能装下3–4条”的工程问题已有改善。

但两个问题仍然存在：

1. Query/Select 看到的 Reference 预览可能只展示部分消息，互补证据可能在 Select 前就没有进入模型视野；Inspect 后虽然可以拿到完整 episode，top-k 和候选排序仍可能挤掉其它来源。
2. 最终装箱当前仍是确定性过程，不会根据问题所需的“证据闭包”重新组合来源。一个候选包含很多原文，不代表它已经覆盖另一个候选所需的第二份证据。

因此，`retrieved` 只能说明某个标注来源出现在返回结果中，不能说明模型 Answer 一定能从返回内容构造完整答案。

## Reflection 与 Search 的边界

本次 Reflection 产生 `127` 条工具决策：`116 reflection_mutation`、`10 reflection_stop`，另有1条工具决策失败；没有真实的 Reflection Inspect、Backlink 或 Evict。Search 的 BFS 统计不能替代 Reflection 的多跳整理证据。

这解释了当前图的形状：Add 可以写出更多 event/fact，但 Reflection 没有先读取旧节点、人物和关系，再决定复用、更新或建立边。结果是“结构数量增长”与“导航质量增长”脱钩，仍可能出现主体归属错误、重复事实和不受来源支持的关系。

## 当前问题的直观链路

```text
原始消息
  ↓
最低 episode 已保存并可检索       ← 本次工程层基本成立
  ↓
Reflection 直接 Mutation           ← 当前主要路径
  ↓
event/fact 增多，但旧节点复用不足
  ↓
Search Query/BM25+Embedding
  ↓
Select 看到的是部分 Reference 预览  ← 互补证据可能在这里消失
  ↓
Inspect/Backlink 补回部分正文
  ↓
最终装箱按候选顺序截取             ← 仍可能缺少证据闭包
  ↓
下游 Answer 只能基于不完整证据回答
```

所以当前最值得修复的不是继续增加节点种类或关系数量，而是把三段证据范围接起来：

`Reference 可见片段 → Inspect 后完整来源 → 最终证据组合`。

## 改进顺序

### 1. 先处理 Reflection 的“先看再写”

保持现有三种 Reflection 状态和 Add/Search 边界，但把 Mutation 前的最小检查变成可观测的硬步骤：

```text
本批 WorkingMemory
  + 已有相关 References
  → 至少一次 Query 或已知 ref 的 Inspect
  → 必要时 Backlink 找旧关系
  → 模型决定复用 / 更新 / 新建 / no-op
  → Mutation
```

这里的“至少一次”不是固定增加一次昂贵模型调用，而是要求 Mutation 的来源证据能指向本批消息或刚刚读取的旧节点；若模型选择直接 Mutation，记录 `orientation_skipped`，作为后续质量检查。只有跨会话更新、冲突、遗忘、人物和关系题才需要强制加入旧节点探索；纯粹的最小 episode 投影不应被迫重复整理。

### 2. 让 Reference 预览覆盖“互补证据槽位”

当前 Reference 叙事已经包含类型、来源和命中片段，但对长 episode 仍可能只展示开头或单一命中。下一步在不恢复完整 Context 的前提下，为每个候选保留少量互补片段：

- 问题中出现的人物、时间、地点、动作分别保留命中片段；
- 同一来源中相邻的支持句成组展示；
- 明确标出 `shown_ranges` 和 `omitted_ranges`，让模型知道需要 Inspect；
- Query 分支合并时保留不同分支的片段并集，而不是只保留最高分片段。

验收重点用 L04、qa-11、qa-15：分别检查来源是否在 Reference 中可见、Select 是否排除、Inspect 是否补回、最终装箱是否保留。

### 3. 用受限 LLM 做最终证据装箱对照

先不改变正式 Search 默认行为，做离线同轨迹对照：给模型 `question + 已选证据片段编号`，只允许返回已有片段编号和顺序；系统再按编号展开原文、去重、校验来源和字符预算。记录模型选择、预算丢弃、证据闭包、延迟和与确定性装箱的差异。模型不能新增事实、改写来源或创建新 ref。只有对照证明稳定改善，才考虑接入默认 Search。

### 4. 最后校准缓冲触发

本次完整运行中，Reflection 频繁发生且许多 mutation 失败，说明“是否启动整理”和“这次 mutation 是否有价值”仍耦合。应分别观测 accepted/settled 水位、WorkingMemory 数量和字符数、会话切换/冲突/遗忘硬信号、旧记忆探索、mutation/no-op 结果及失败原因。先用长历史连续 Add 验证“积累后再整理”的收益，再调整默认阈值，不把每次 Add 都强制变成 Reflection。

## 结论边界

本次运行确认：

- 最低 episode、BM25/Embedding、Search BFS、Select 和观测链路都已实际工作；
- Add 工程成功率较旧基线提高，Search 外壳达到100/100；
- Reflection 尚未实际形成“先 Search/Inspect/Backlink、再 Mutation”的稳定路径；
- 多跳和复合证据质量仍明显受 Add 失败、Reference 预览、Select 视野和最终装箱影响。

因此，当前 AM-Link 已具备可持续实验的基础设施，但还不能宣称结构化记忆图或最终回答效果已经修好。下一轮应优先做可控的 Reference 覆盖、Reflection orientation 和装箱对照，再扩大真实题量。
