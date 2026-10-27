# AM-Link 二期协议

本文描述0.2.1的当前协议。工程修复和实际验证边界见[修复报告](../docs/doing/2026-10-11-amlink-core-repairs.md)，不代表已通过官方评测。

## Add

`POST /v1/memory/add` 接受 `request_id`、`user_id`、`session_id` 和一个或多个带
`role`/`content`/可选 `timestamp` 的消息。请求先以原文形式持久化并按
`(user_id, request_id)` 幂等。只有 RawEvent、episode、词法索引以及开启时的
episode 向量全部完成；若已触发Reflection，还必须等待该轮Mutation/no-op终结后，才返回成功响应。Reflection 是否触发不改变成功 Add 的
接口形状；尚未整理的内容仍通过 episode 可被后续 Search 检索。

本地默认期限1740秒，含Add锁等待。已触发请求按稳定目标水位分批消费；成功批次持久推进，失败请求重放时继续尾部，不由系统内部重试。逐请求episode/词法/向量检查与Reflection水位分开，不能因为后来请求完成Reflection，就把此前索引失败的请求标为成功。

2026-10-27内部协议：冻结计划v2保存原文版本、连续字符范围及主要/背景归属。节点/关系草案后由程序直接调度联合审查和提交，不暴露纯控制commit/validate工具。原文段主要归属恰好一次；全部组完成才推进原始消息水位，失败重放跳过已完成组。旧未完成计划版本显式拒绝，不静默迁移。

联合审查可修订节点正文、日期和支持来源，撤销无依据的节点或边；保留边必须重新核对已修改端点。完整材料装不下则按依赖分页，保持来源位置编号。真正无增量需明确理由并保存episode_only完成凭据；依赖/预算/协议失败与真实未完成更新不得转成空成功。全文和模型指纹均未改变时可复用节点向量，仍原子写入新增支持。

## Search

`POST /v1/memory/search` 接受 `user_id`、`query`、`top_k` 和可选 `options`，返回
`{"data": [{"id", "content", "score", "created_at"}]}`。返回内容是已保存
MemoryItem 与必要原文来源组成的证据卡片，保留状态、角色、会话、顺序、关系和
来源引用。Search 不读取 WorkingMemory，不使用任务标注，也不代答。

内部 Search 顺序为：

```text
Query(question)
  -> BM25 + embedding 各分支
  -> 分支合并
  -> select(References 子集及顺序)
  -> BFS: Inspect(ref)->Item + Backlink(ref)->References->select
  -> Search 语境与证据装箱
```

`Inspect` 读取已知 ref 的节点正文及正向关系；`Backlink` 读取指向该节点的入边
候选。两者的结果都进入下一轮模型决策，最多受到配置的跳数、节点数、邻居数和
工具步数限制。每个 Reference 同时包含语义化 ref、kind、显示标签、命中片段、
来源和状态，不能只把孤立编码交给模型。

Select默认只输入question和候选叙事，不复制完整context；多页局部筛选后统一筛选排序。最低 episode 的候选叙事最多保留若干互补来源片段，并带来源、角色、序号、shown range 和 omitted source 信息；完整来源仍由 Inspect 展开。合法空子集是正常结果。coverage仅保留引用实际选中位置的说明，作为后续可核验导航说明，不能替代来源正文；无效辅助说明单独记账。最终证据卡片遵守候选顺序，`score`表示返回次序（1、1/2、1/3…），不是概率或旧BM25分数。输出保留来源时间，重复来源正文可引用前卡片；不足篇幅时返回明确标记的片段，内部轨迹记录 evidence units、闭合状态、省略内容和原因。

## 错误与重试

2026-10-23内部细化：每次投影冻结编号References；Inspect按本次提供的引用/页组合读取，范围与正文digest一起记录。成功读取不等于模型已经读到，下次主决策回执记录实际可见范围。Search最终卡片可包含同一路径的多个MemoryItem，id为已有根ref；内部指标标记`packing_unit=evidence_group`。普通Reflection跨至少2个Add积累，触发后冻结前缀；失败重放不扩大目标。公开请求/响应字段不变，详细行为以根DESIGN为准。

后续闭环修复：回执统一收集所有实际正文容器；阅读记录与可见记录分开，隐藏页可以重读。Reflection非法边阻止整批提交并在有界loop内反馈，不自动翻转；没有新材料的同错误提案显式失败，不改为空成功。空旧资格范围由数据库核验，不伪装成一次Query。Workspace格式v2清除旧格式阅读凭据；可选来源页可折叠，必需正文仍受保护。程序无权把类型合法当成语义正确，真实验证限制见最新实施报告。

无内部重试、后台补偿或模型故障降级。幂等成功重放不再次调用模型；未完成请求
可在官方重放时继续必要阶段。模型、embedding、索引和结构校验失败分别保留明确
错误，不能把空结果或部分完成伪装为成功。
