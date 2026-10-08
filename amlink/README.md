# AM-Link 二期方法

状态：设计初稿，尚未接入比赛服务。

`amlink/` 是二期实现的独立边界。`archive/phase-1/` 继续作为一期 0.3.0 的冻结参考；`dataset/`、`benchmark/` 和 `visualization/` 负责研究数据、靶场和观测，不直接承担二期服务实现。

本目录的设计同时受三类材料约束：

- 当前数据集和案例研究揭示的真实难点：时间、更新、冲突、去重、分子分母、人物归属、隐私、遗忘和多跳证据；
- 一期源码已经验证的事务、幂等、user_id 隔离、原始事件、版本事实、混合检索和降级边界；
- TinySoul-Agent 的热缓存、daily/ref、Reflection、Inspect/Search 分工，以及渐进披露和可追溯引用思想。

比赛边界保持不变：AM-Link 只提供 Add/Search，主办方负责 Answer/Eval。二期不把 TinySoul 的完整 Agent 循环、Jev 或内部思维链带入服务；内部模型调用固定使用 `gpt-4o-mini`，embedding 是可替换的合规提供方，当前实验基线沿用 `embedding-3`。

阅读顺序：

1. [DESIGN.md](./DESIGN.md)：总体架构、Add/Search 链路、ref/Inspect/Search 语义和失败边界；
2. [PROTOCOL.md](./PROTOCOL.md)：比赛 API 与内部设计对象的对应关系；
3. [DISCUSSION.md](./DISCUSSION.md)：直观解释、决策记录和每轮讨论的待定问题；
4. [MVP.md](./MVP.md)：当前第一版建议；WorkingMemory/MemoryItem 分工、统一类型与引用、正反向检索和有界多跳；
5. [PLAN.md](./PLAN.md)：分阶段实施、验收门槛和待讨论取舍。

设计稿中的“应当”是待实施方案；只有标为“已验证”的内容才代表当前代码或实验事实。
