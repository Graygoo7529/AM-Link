# AM-Link 二期实施计划

状态：设计初稿，等待方法方案讨论后进入实现。

实施原则：按 [MVP.md](./MVP.md) 验证 `RawEvent + WorkingMemory + 带 kind 的 MemoryItem + 引用关系`。不同记忆类型共用存储；第一版支持正向/反向查询和有界多跳。大量类型专有字段、持久 EvidenceCard/evidence_group 和完整模型工具循环继续延后。

## 阶段与验收

| 阶段 | 内容 | 验收门槛 |
| --- | --- | --- |
| P0 | 固定 contract、数据集输入适配、内部 schema、26 个案例的输入/输出边界 | 明确 user/session/role/timestamp 的来源和缺失；不把答案、rubric 或未来事件写入 Add；所有案例都能说明必要证据 |
| P1 | 原始事件、幂等、user_id 隔离、热缓存、原文检索 | Add 原子提交；重放不重复；Add 后立即 Search 能找到原文 |
| P2 | 统一 MemoryItem/kind/ref、about/contains 与三种状态/事件关系、有来源的 reflection mutation | 新原文和相关旧节点共同进入整理；原文/节点/关系可追溯；提交后才推进 WorkingMemory 位置 |
| P3 | 精确 Inspect、派生 backlinks、有界多跳、混合候选与时间/状态过滤 | 控制深度、节点数和正文预算；环去重；已撤回内容不回流；观察真实访问路径 |
| P4 | `gpt-4o-mini` query plan、候选 select/rerank、embedding 对照 | 只输出 ref/rank/filter；调用次数、tokens、延迟和失败可观测 |
| P5 | benchmark 适配、可视化运行轨迹、案例回放和 holdout | 26 个案例可切片运行；理论链路与实际轨迹可逐项对照 |
| P6 | 小规模真实 provider 回放、容量和费用校准 | 分别报告召回、完整证据、延迟、模型调用、费用和错误；未通过不部署 |

## 第一轮实验顺序

1. 用 raw + lexical 基线跑 LM04、LM05、BEAM B02、PV04，验证失败归因和观测完整性；
2. 加入统一 kind、about/contains 和三种状态/事件关系；追加 LoCoMo L04，检查人物、概念及原文关联；
3. 固定同一份 Add 产物，比较不展开、一跳、最多三跳；另比较无类型条目基线。先确定性读取，再评估有限 query plan/select 的额外收益；
4. 通过同一切片比较 embedding-3 和 lexical 的互补召回，不把“命中相似句”当成完整证据；
5. 最后再测试 Add reflection 的阈值、批量大小和 `gpt-4o-mini` 调用预算。

## 还需要讨论的取舍

- 热缓存达到阈值时，是在当前 Add 内同步整理，还是只记录待整理状态并依赖下一次 Add；前者更及时，后者更省延迟但会延迟结构化事实；
- Search 是否默认调用一次 query plan，还是只对时间、冲突、多跳和聚合问题调用；后者成本更低，需要可靠的复杂度判断；
- ref 结果是返回 fact 与 source 的两项，还是组合成一张 EvidenceCard；前者更透明，后者更容易在官方 Answer 的上下文预算内保持证据闭包；
- embedding-3 是否作为二期默认模型，还是先用可替换接口完成无外部依赖基线，再以固定切片证明收益；
- 同一事件存在冲突时，Search 默认返回双方，还是按 query 明确要求的“当前状态/历史状态”过滤；默认保留冲突更安全，但可能增加 Answer 负担。
- 同名人物、别名和重复事件如何复用身份；不确定时先保留独立节点；
- 多跳的节点/邻居/正文预算，以及来源原文作为终端证据的读取额度；预算不足不应被写成“无此事实”。

这些取舍都不影响外部 Add/Search contract；应以公开小样本收益和成本边界决定，而不是先凭直觉固化。
