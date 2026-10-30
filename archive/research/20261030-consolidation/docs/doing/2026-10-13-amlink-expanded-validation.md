# AM-Link 0.2.1 扩展真实链路验证

更新日期：2026-10-13。本文记录 2026-10-12 的中断重跑、2026-10-13 的 21 个跨数据集锚点和三个定向复验。它们是方法诊断，不是官方 Smoke/Full，也不执行 Answer。真实模型为已授权配置的 gpt-4o-mini 与 embedding-3；provider 未提供可核验 token/价格汇总时，调用成本记为未知。

## 运行边界

| 运行 | 范围 | 状态 | 可用结论 |
| --- | --- | --- | --- |
| `amlink-repaired-locomo-100-real-20261012k` | LoCoMo 100 题、145 Add | 完成，较早修复版 | 完整旧基线：Add 68/145，Search 99/100；具体见 [100 题分析](./2026-10-11-amlink-100-rerun-analysis.md) |
| `amlink-repaired-locomo-100-real-20261012m` | 计划 100 题；执行中断 | **部分运行，不是完整复跑** | 44 Add 请求中 41 成功；25/25 Search 成功；163 节点、55 边；仅作中途缺陷诊断 |
| `amlink-cross-*-20261013m` | 7 类公开数据集的 21 个锚点 | 完成 | 35 Add、21 Search；可用标签的 12 题单独评分 |
| `amlink-targeted-{l4,p2,v32}-20261013m` | 三个失败锚点 | 完成 | 核对局部修复和 fail-closed 遗忘，不作为总体效果估计 |
| `amlink-repaired-locomo-100-real-20261013n` | LoCoMo 100 题、145 Add/100 Search | 正在进行 | 完成后另行补入结果；没有报告前不作全量结论 |

运行目录都在被忽略的 `benchmark/data/runs/`，未把原始对话或完整轨迹复制到本报告。跨数据集的 21 个运行已经由靶场登记到本地研究工作区，可重建可视化。

## 跨数据集汇总

运行选择 `scope=anchors`，每个案例只添加案例目录绑定的范围，通常很短；它适合对照某个证据链，不等同完整数据集或长程历史。下表中的 evidence recall 按作者标注的目标证据计数；没有可用 evidence 标注的搜索只报告 API 成功，不计入准确率。

| 数据集 | 锚点 | Add 成功 | Search 成功 | 可评分题 | top-5 证据命中 | 完整链 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LoCoMo | 4 | 8/9 | 4/4 | 4 | 8/11 | 3/4 |
| LongMemEval | 7 | 15/15 | 7/7 | 6 | 14/14 | 6/6 |
| BEAM | 2 | 2/2 | 2/2 | 0 | 不适用 | 不适用 |
| PerLTQA | 2 | 2/3 | 2/2 | 2 | 2/2 | 2/2 |
| PersonaMem | 2 | 2/2 | 2/2 | 0 | 不适用 | 不适用 |
| MAB | 1 | 1/1 | 1/1 | 0 | 不适用 | 不适用 |
| PV3 | 3 | 2/3 | 3/3 | 0 | 不适用 | 不适用 |
| **合计** | **21** | **32/35** | **21/21** | **12** | **24/27** | **11/12** |

`Search 21/21` 只表示接口和方法 loop 正常结束。12 道可评分题合计 27 个 gold evidence targets，top-5 找到24个；完整链覆盖 11/12。这个小样本结果不能外推为竞赛准确率，尤其 BEAM、PersonaMem、MAB、PV3 的这些锚点没有可用于该口径的 evidence 标签。

## 典型链路

### LoCoMo L04：人物关系问题，返回不等于证据闭合

L04 问 Joanna 和 Nate 的共同兴趣，作者标注需要 7 个来源证据。较早的跨数据集运行 Add 4/5，top-5 命中 4/7；新的定向运行 Add 5/5，命中 5/7；两次 Search 都成功，但完整链均为 0。新运行在 top-5 里仍缺 2 个来源，因此即使接口成功、单条 evidence recall 看起来过半，下游仍无法得到完整集合答案。

实际 Mutation 提出了不少 event 以及 `contains`，但不兼容端点的边被记录并过滤；新库中没有稳定的 person 节点导航。此前 L04 的真实错误还显示 event 正文与 raw 来源可以语义错配。该案例说明：结构校验能避免非法图边，却不能证明“来源真的支持这个主体/事件”；需要评估证据片段、speaker、claim 和节点之间的语义归属，不能用边数当图质量。

### LongMemEval LM04：窄切片可成功，但不等于跨会话图已验证

LM04 的开销问题在 4/4 Add、1/1 Search 下找回 4/4 个标注来源，完整链为 1。图中是两个 event 和两条 contains，没有 person/entity/concept，也没有 Reflection Inspect/Backlink。它证明 episode 与 event 的组合在该切片能给出所需原文，不证明长历史下的重复归并、身份稳定或多跳图导航有效。

### PerLTQA P02 与 PersonaMem PV3：遗忘必须拒绝未授权内容

初次 P02 运行中，模型提出两条 `forget`，校验因新消息不含明确授权而拒绝该 Mutation；Add 未成功，但之前写入的最小 episode 仍在，Search 仍成功。定向新运行中该模型输出没有重复相同 forget，Add 2/2 成功，说明首次错误具有模型输出随机性，不能称为代码修复已消除。

PV3 `v32` 首次失败是 mutation 引用未知旧记忆；定向复验中则改为提出未明确授权的遗忘，仍被 fail-closed 拒绝。系统没有执行删除。不同模型输出触发不同验证错误，说明 Mutation 需要对无效关系采取局部隔离，同时对遗忘保持严格拒绝；这两种边界不可混为“全部容错”。

### BEAM：是否 no-op 也是有效的整理决策

两个 BEAM 锚点均 Add/Search 成功且没有 gold evidence 可评分。其中一个 Mutation 建出一条 episode→event `contains`，另一个用 stop/no-op 保留最小 episode。锚点很短、未带评分标注，因此只能说明整理器会做不同选择，不能判断哪一种记忆抽象对完整 BEAM 长对话更有效。

## Reflection 与图结构实测

21 个锚点的真实 Reflection 决策共 **14 次 Mutation、5 次 stop**；没有观察到 Reflection 内 `Inspect`、`Backlink` 或 `Evict`。四个运行无 Reflection 调用，多数其余运行只发生一两次决策。各独立运行最终累计 47 个节点和 9 条边：37 episode、9 event、1 fact；9 条边全部是 `contains`。没有 person、entity、concept，也没有 about、supersedes、contradicts、same_event_as。

与之相对，标准 Search 真实执行了 **43 次 Inspect、12 次 Backlink**，说明可见引用上的 BFS 操作确实进入了真实路径。21 个锚点没有触发 Select，也没有查询扩展调用：候选规模太小，所以这组运行不验证高候选精炼、多分支合并或 Select 排序质量。

这揭示两件事：

1. Reflection 工具虽然可用，模型在这些短锚点中仍主要直接 Mutation 或停止；它没有实际使用旧图探索来避免重复/改善主体链接。因此，设计中的 Reflection BFS 目前是“实现可调用、真实策略未证实”。
2. 结构主要是最低 episode 加少量 event。没有足够证据证明多跳链、跨会话身份或关系图成为有效 Search 导航。需要使用完整/连续 Add，而不是只跑 anchors 来检验缓冲价值和触发时机。

运行操作数记录到 retrieve 404、model 192、context 126、extract 70、store 51、index 42、Reflection 52、Add 35、Search 21。候选调用很多不等于证据链正确；provider 未给可核验用量时 token/费用均未知。

## 局部修复及验证

### 代码回归

当前本地 `amlink/tests` 与 `benchmark/tests` 共 **60 项通过**。本轮增加的行为是：

- Select 页内位置中有合法选择且夹杂页外编号时，保留合法项并记录被丢弃项；不再因额外编号丢弃整页。无合法项仍显式失败。
- Mutation 对已知但没有归属目标的顶层时间字段作有记录的过滤；未知顶层字段仍是 schema error。
- self-link、未知旧 ref 和关系端点类型不兼容时，过滤具体无效边并保留可验证的节点；source ref 仍须属于当前 user 且存在。
- Forget 授权仍严格要求本批新消息中的用户明确表达遗忘；缺少授权不执行删除。P02/V32 的拒绝仍会导致当前 Mutation/Add 失败，这是可见的 fail-closed 成本，不是一个已解决项。

这次未调整固定缓冲阈值、Query 扩展、Select 语义、证据截断算法或最终装箱，也没有把 Answer/LLM 装箱加入 Search。60 项回归不是方法质量测试。

### 定向真实复验

| 运行 | Add | Search | 证据结果 | 解释 |
| --- | ---: | ---: | --- | --- |
| L04 | 5/5 | 1/1 | 5/7，完整链 0 | schema 错误不复现；仍有两份关系来源未返回，主体归属和集合装箱未解决 |
| P02 | 2/2 | 1/1 | 1/1，完整链 1 | 本轮模型未再次提出无授权 forget；不证明拒绝路径变化 |
| PV3 v32 | 0/1 | 1/1 | 无可评分 gold | fail-closed 拒绝模型提出的无明确授权 forget；没有执行删除 |

定向调用只用于重现原问题附近的行为。由于同一数据切片每次重新调用模型，模型输出会变化；不可将新一次不同输出视为同一输入的确定性消融。

## 2026-10-12 部分 100 题运行发现

run `...20261012m` 因执行被中断，没有 `report.json`。其观测中出现 44 条 Add trace（41 成功、2 次 `mutation_schema_invalid`、1 次 `mutation_self_link`）及 25/25 成功 Search；Reflection validation 过滤了 **30 条 `relation_type_mismatch` 边**，有效节点仍提交，最终 163 个节点、55 条边。它是随机运行中的中途快照，不能与完整 100 题 `...20261012k` 指标合并。

这 30 条坏边既验证了“关系端点错不应让整批正确节点一起回滚”的局部修复，也说明模型仍大量把 event-to-event 建成 `contains`。局部过滤防止数据丢失，但不会自动生成正确关系。Self-link 和错误根字段的新增处理有单元回归；完整真实命中情况需看 `...20261013n` 完成后的报告。

## 进一步设计结论

### References 与模型可见证据

每个 Search 都成功，窄锚点里 24/27 个 gold evidence 在 top-5，但 L04 仍缺两项。候选片段、来源标注及 Select 的局部容错能让调用完成，却未解决不同消息间的互补性。下一步应沿同一 Search span 比对 query 分支片段并集、Select 输入/输出、Inspect 正文覆盖和最终装箱的 source set；不要先凭总召回率扩大候选预算。

### BFS 与 Reflection orientation

跨切片真实 Reflection 0 次 Inspect/Backlink；部分 100 题运行也未证明 Reflection 使用图工具。当前“每批一次 orientation Query + 之后模型决定要不要 Search/Inspect/Backlink”的边界需要实测：如果 orientation 已有高相关引用，模型为何直接 Mutation/stop？下轮在连续 Add 的长历史切片观测每个 `reference_position`、旧节点是否进入上下文、模型是否读原文和引用叙事，再调整提示/预算。

### WorkingMemory 与时机

锚点模式通常只有 1–5 个 Add，无法验证积累后全局 Reflection。需要至少三个完整连续历史条件：未达阈值、跨会话边界、硬更新/冲突。逐条列出 accepted/settled watermark、buffer 数/字符、触发原因、目标快照和 Reflection 步数。只看 Add p95 不能说明缓冲真的改善整理。

### 最终证据装箱

Search 仍使用确定性装箱，没有 LLM 装箱实测。L04 的完整链为 0，即使增加顶层位置容错也不改变它。下一步适合在同一数据库/相同探索轨迹做离线配对：现行装箱 vs 模型只挑已有证据片段编号和顺序、系统再按来源展开的受限装箱。记录目标证据 set、重复来源、超预算丢弃、可读原文、顺序和延迟；任何模型无法引用或新造证据。

### 方法评估优先级

1. 等 `...20261013n` 全量报告；分别按全体 100 题、Add 成功前提子集和类别报告，不混入未完成的 `...20261012m`。
2. 用长历史连续 Add 验证 Reflection 延迟整理、多跳探索和跨批 Workspace；锚点只能辅助定位单链路缺陷。
3. 选 L04 / qa-11 / qa-15 等可见证据失败，在完全相同数据库和已记录候选集上做片段呈现与装箱配对。
4. 若模型仍不调用 Reflection Inspect/Backlink，再调整工具提示和决策语境；先以轨迹证明“为什么没读”，不直接增加固定 query 数或 kind 比例。
5. Answer 仍留在靶场下游诊断，不放入比赛 Search API；公开榜单准确率仍要由官方 Answer/Eval 给出。
