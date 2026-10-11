# AM-Link 二期重构实施与真实回归

日期：2026-10-11

本文记录二期重构从计划进入实现后的核对结果。它是本地方法和靶场研究报告，不是官方 Smoke、排行榜成绩或 Answer/Eval 结论。

## 实施范围

旧二期实现已归档到 `archive/phase-2/amlink-0.1.0/`，当前实现为 `amlink/` 0.2.0。核心变化如下：

- Add 先不可变追加 RawEvent，再为每个成功请求生成保留角色、会话、顺序和原文语境的最小 `episode`；完成 BM25 与 embedding 索引后才返回成功。
- WorkingMemory 跨 Add 保留；按积累阈值、明确更正/遗忘、会话切换等条件触发 Reflection。未触发 Add 不调用 Reflection，仍可直接被标准 Search 通过 episode 检索。
- Reflection 使用独立的持续 MemoryContext 和结构化 tool calling，可 Query、Inspect、Backlink、Evict，再提交 Mutation 或 no-op；同一 user 的 Reflection 串行，失败不做内部重试。
- 标准 Search 每次新建独立语境，只读取结构化 MemoryItem。完整复合语义是 Query（BM25 + embedding，必要时查询扩展）→ 分支合并 → Select（筛选并排序）→ LLM 驱动的有界 BFS（Inspect/Backlink/Stop）→ 确定性装箱。RawEvent 只作为已选 Item 的来源回溯。
- 模型输入使用有界叙事投影，Select 单独限制模型候选数；完整输入和每个截断原因仍保留在 native 观测 artifact。可视化新增 `--max-queries`、`--max-spans`，只压缩浏览投影，不改变运行档案。

## 验证结果

本地 `amlink/tests` 与 `benchmark/tests` 共 39 项通过。覆盖最小 episode 的即时可检索性、幂等 Add、WorkingMemory 阈值触发、Mutation 来源校验、语义新 ref、用户内 Add 串行，以及 raw 模式不调用模型。

真实模型使用已授权的 OpenAI 兼容 `gpt-4o-mini` 与 embedding-3 配置；凭据没有写入报告或代码。

### 单案例回归

运行 `amlink-refactor-final-smoke3-20261011` 使用 LoCoMo L01 的两个锚点 Add 和一个 Search，配置为 graph、embedding 开启、Reflection 3 步、Search 3 步、Select 候选上限 24；这是在 Select 重复 ref 归一化和 lineage 截断后的最终小回归。

- Add：2/2 成功；Search：1/1 成功。
- @5 evidence recall=1.0、hit rate=1.0、chain coverage=1.0；@1 evidence recall=0.5，表示两个标注证据都在前五条，但第一条只覆盖其中一个。
- 观测 44 个成功步骤，包含 7 次 embedding-3 和 4 次 gpt-4o-mini；没有模型、结构化 Mutation 或存储错误。
- 该结果说明“episode → Query → Select/BFS → 最终证据”的链路可运行，不足以推断长历史或全量准确率。

### 100 问题 LoCoMo 研究切片

运行 `amlink-refactor-locomo-100-real-20261011` 是修复前对照；`amlink-refactor-locomo-100-real-20261011b` 是加入模型语境和 Select 候选预算后的重跑。两者都使用四个完整历史记录、前 25 个任务，共 100 Search、2080 条历史消息；这是当前 26 个案例研究规模的约 3.8 倍。运行目录在被忽略的 `benchmark/data/runs/`，可由 workspace 注册表重新加载。

修复前的主要失败是：Reflection/Select/BFS 模型输入超过 80,000 字符，导致大量 `model_input_budget`，Search 无法进入可评价阶段。修复后运行 `...-20261011b` 完成 145 Add 和 100 Search：Add 成功 41/145，Search 成功 92/100；Search @1 evidence recall=0.176829、hit rate=0.25、chain coverage=0.13，@5 分别为 0.432927、0.56、0.33，MRR=0.382。按类别，single-hop @5 三项均为 1.0，multi-hop evidence recall@5=0.366667，temporal=0.464286，open-domain=0.571429。失败主要来自 Add 侧 `model_input_budget` 96 次、结构化 mutation 校验 8 次，以及 Search 的重复/未知 Select ref 8 次；修复后没有出现新的 Select 输入预算错误，但模型仍会重复返回同一 ref，当前系统已去重并记录无效 ref。

这组结果说明有界模型语境解决了“整个流程被输入预算阻断”的工程问题，但没有自动解决长程检索质量：57 个查询的来源 Add 失败，且 multi-hop/temporal 仍明显低于 single-hop。下一步应优先减少 Reflection 对高噪声长历史的失败、改善 Mutation 工具输出的来源约束，再分析关系图是否真的增加了跨会话召回。

在此之前还保留了六个跨数据集切片的真实运行档案（LoCoMo、LongMemEval、BEAM、PerLTQA、Life、Persona），用于检查不同数据结构能否进入同一 Add/Search/观测协议；它们的早期失败已经推动了 tool calling 单工具约束、语义 ref 规范化、episode 关系过滤和 Select 术语统一。当前 100 问题 LoCoMo 运行是对链路压力最大的持续回归，不把它误写成所有数据集的质量排名。

这次对照已经确认一个方法事实：结构化记忆越多，不能把完整节点正文、来源、边和候选全部原样塞给每个模型调用。必须把“完整可追溯存储”和“有界、可解释的模型叙事视图”分开，并记录候选在未召回、预算截断、Select 排除、BFS 未扩展、装箱丢弃中的位置。

## 可视化与复用

大运行的完整 `observability.jsonl`、`trace.jsonl`、`report.json` 和 SQLite 保留在运行目录；统一网页默认每题最多显示 20 个问题和全部已投影步骤。大型运行可使用：

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --workspace `
  --workspace-run amlink-refactor-locomo-100-real-20261011b `
  --max-queries 3 --max-spans 60 --web
```

页面会显示每题“展示步骤/完整步骤”，并说明省略只发生在页面投影。下次加载研究可视化时，先读 `visualization/README.md`、workspace 注册表和本报告，不需要重新调用模型。

## 仍待验证

- 官方 Smoke 与真实 HTTP 部署；本轮没有恢复一期服务器，也没有提交凭据或数据库。
- 目标 Add 并发下的排队、p95/p99 延迟和请求时限；当前实现使用有界 user lock，Reflection 串行。
- 长程人物身份、近义重复、冲突关系和跨会话关系边的质量；单案例成功不能代替完整关系评估。
- provider usage/费用字段。当前服务响应没有稳定返回价格信息，观测明确记录为未知，不从调用次数臆造费用。
- Answer/Eval。AM-Link 仍只返回证据，靶场 Answer 诊断不能当官方成绩。
