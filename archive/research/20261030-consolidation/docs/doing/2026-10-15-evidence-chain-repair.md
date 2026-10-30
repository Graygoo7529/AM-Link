# 2026-10-15 证据链修复

状态：三项本地实现已有回归及确定性切片；真实模型复验报告网络错误，10月20日探测定位到本机 socket 权限阻断，不能归因于供应商。10月23日提交审查进一步修复了来源上限、复用/缺失账本和无关探索通过门槛的问题，见[提交前检查](./2026-10-23-commit-readiness.md)。

2026-10-16 校准：闭合状态现在只有在来源完整展示（或已在前卡片完整去重）时才标记为 `complete`；仅展示局部片段会进入 `partial_source_units`。

本轮针对 2026-10-14 100 题重跑发现的三个断点实施了第一版修复：Reference 可见范围不足、Reflection 直接 Mutation、最终装箱缺少证据闭合。标准 Add/Search 接口没有改变，Search 仍使用独立语境，Reflection 仍是 Add 内部的持续 Workspace。

## 已实施

### Reference 互补片段

`amlink/evidence.py` 新增互补片段投影。对于一个最小 episode，Select 输入可从不同 Query 分支和不同来源消息取得多个短片段，而不是只展示一个长正文片段。每个片段带有：

- `source_ref`、角色、消息序号和来源时间；
- `shown_range`、原文字符数和展示字符数；
- 是否为完整消息；
- 未展示来源及预算原因。

这仍然是模型可见投影，不改变 RawEvent、episode 或长期记忆内容。完整原文仍由 Inspect 和最终装箱按需读取。

Select 多页合并时不再把命中片段压成没有来源含义的字符串，保留片段对象、覆盖信息和范围。这样可以区分“来源已召回但只展示了局部”和“来源根本未进入候选”。

### Reflection 先看再写

内部 `reflection_mutation` tool 增加三个依据字段：

- `basis`：`new_information`、`update_existing`、`resolve_conflict`、`identify_person`、`add_relation`；
- `inspected_refs`：模型实际查看过的旧记忆引用；
- `no_prior_match`：纯新信息在 orientation 后没有旧匹配时的明确声明。

每次触发 Reflection 仍先做一次有界 orientation，并记录 `orientation_refs`。若 Mutation 涉及更新、冲突、人物身份、关系，或包含已有节点/关系，则必须在当前 Workspace 的 `Inspect` 或 `Backlink` 路径中出现对应旧引用；否则本轮工具调用被记录为 `reflection_orientation_required`，模型继续获得下一轮工具决策机会。纯新信息不被强制增加图探索，但可以明确声明没有旧匹配。最低 episode 投影不受此门槛阻塞。

这个门槛只约束 Add 内部结构化 Mutation，不改变公开接口，也不将标准 Search 与 Reflection 合并。

### 确定性证据闭合

最终装箱仍不调用 LLM。对每一张返回卡片，观测中新增逐来源 `evidence_units` 和 `closure`：

```text
MemoryItem
  -> source_ref
  -> shown range / complete or partial
  -> included or omitted reason
```

装箱继续遵守 Query/Select 的候选顺序，去重已经完整展示的来源，并优先保留完整消息；但不会再把“返回了一个 episode”当成“所有来源证据都已闭合”。被预算、重复来源、top_k 或状态过滤的对象会留下具体原因。受限 LLM 装箱仍只计划作为离线对照：它只能返回已有 evidence unit 的编号和顺序，不能产生新事实。

## 本地验证

```text
amlink/tests benchmark/tests: 64 passed
py_compile: passed
```

新增回归覆盖：

1. 多来源互补片段和字符范围；
2. 长消息的局部展示范围；
3. 风险 Mutation 在没有旧记忆探索时被门槛拦截；
4. 已探索的旧引用可以通过门槛。

测试使用工作区内独立临时目录。系统默认的 `B:\tmp` 和 pytest cache 仍受当前权限保护，不影响测试断言。

## 2026-10-16 验证结果

本地原文模式 l4 anchors 切片 `amlink-evidence-chain-l4-20261016-local` 完成 5/5 Add、1/1 Search，未产生错误。该配置关闭 embedding 与模型，所以它验证的是 BM25/确定性路径及观测、装箱契约，不是 Select 或 Reflection 的语义质量。@5 evidence recall、hit rate 和 chain coverage 均为 1.0；5 张证据卡的 closure 均为 complete，7 个来源证据单元全部包含且完整，`omitted_refs` 与 `partial_source_units` 均为空。@1 recall 为 0.428571，说明窄预算下首位候选排序仍会影响证据完整性，但不是 @5 的闭合装箱漏证据。轨迹中可见 Query merge、Inspect、Backlink、BFS、证据单元和最终装箱事件。

随后使用相同的原文模式验证时间与跨会话多跳案例，并运行冲突案例检查装箱与观测接线：

| 案例 | Add / Search | @1 证据召回 / 链覆盖 | @5 证据召回 / 链覆盖 | 装箱闭合 | 解读 |
|---|---:|---:|---:|---|---|
| L04 共享兴趣、多来源覆盖 | 5/5，1/1 | 0.429 / 未覆盖全链 | 1.0 / 1.0 | 5 项完整；7/7 来源完整 | 多来源证据在较宽预算下闭合；首位仍不够完整 |
| L02 相对时间定位 | 1/1，1/1 | 1.0 / 1.0 | 1.0 / 1.0 | 1 项完整；1/1 来源完整 | 本地原文检索命中时间证据；不验证语义抽取/回答 |
| L01 跨会话语义关联 | 2/2，1/1 | 0.5 / 0.0 | 1.0 / 1.0 | 2 项完整；2/2 来源完整 | 两条链路证据都在候选中，但要到 @5 才齐全 |
| B02 经历冲突 | 1/1，1/1 | 无 gold evidence | 无 gold evidence | 1 项完整；2/2 来源完整 | 只验证冲突切片运行与闭合记录；该计划未提供可评分 gold evidence |

L01、L02、B02 的原文模式运行 ID 分别为 `amlink-evidence-chain-l1-20261016-local2`、`amlink-evidence-chain-l2-20261016-local2`、`amlink-evidence-chain-b2-20261016-local2`。四个运行都在装箱账本中记录了各个来源的完整范围、是否包含及遗漏原因；它们没有执行真实 embedding、LLM Select 或 LLM Reflection。可视化索引已重建，包含本地研究运行与当前数据集/案例视图。

同一 l4 anchors 的真实模型运行 `amlink-evidence-chain-l4-20261016` 仍为 `provider_network` 错误（5 个 Add 全部失败），Search 没有证据；随后对单条时间切片运行 `amlink-evidence-chain-l2-20261016-real3`，embedding 和 gpt-4o-mini 也都由本地调用器报告 `provider_network`，Add/Search 各 0/1。两次结果只证明这些调用没有成功，不能区分本地网络限制与供应商故障，已从方法质量指标中排除。10月20日使用同一二期调用器的最小探测定位到本机 `PermissionError / WinError 10013`；未收到 HTTP 响应，详情见[模型接入经验](../operations/models.md)。这不能追溯证明历史运行的底层原因相同。

## 尚未证明

本轮没有声称真实模型质量已经改善。需要端点恢复后的新切片确认：

- Select 是否真的利用互补片段保留多证据，而不是仍然只保留单一来源；
- Reflection 模型遇到门槛后是否会调用 Inspect/Backlink，而不是连续重复 Mutation；
- 最终 evidence closure 是否改善多跳、时间和集合题的完整链；
- 增加 Reference 片段后的模型输入字符、调用次数和 Add/Search 延迟；
- 关系主体和来源归属是否因此改善。

建议先复跑 L04、qa-11、qa-15、B02、时间更新和一个纯新事实切片，再进行 20 题类别平衡对照，最后才考虑 100 题重跑。

## 真实小切片尝试

2026-10-15 使用现有授权配置运行 `amlink-evidence-chain-l4-20261015`（`l4` anchors，5 Add、1 Search）。本次两个模型端点均返回 `provider_network`，5 个 Add 全部失败；Search 请求外壳返回成功但没有证据，因此 `evidence_recall@5=0` 只反映“源 Add 全部失败”，不评价本轮方法。运行目录在被忽略的 `benchmark/data/runs/` 下，未把凭据写入记录。待网络端点恢复后，应使用相同切片重新运行并比较 Reference 片段、Reflection 门槛和 evidence closure 事件。
