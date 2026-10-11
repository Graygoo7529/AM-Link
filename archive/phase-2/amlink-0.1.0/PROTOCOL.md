# AM-Link 二期协议边界草案

状态：0.1.0 本地协议已实现；具体默认值见 [README](./README.md)。本文把比赛外部协议和内部方法对象分开，避免内部结构泄露为未获官方批准的 API 扩展。

第一轮内部边界见 [MVP.md](./MVP.md)：RawEvent、WorkingMemory 活动视图、统一 MemoryItem/kind/ref，以及 about/contains 和三种状态/事件关系。Inspect 与 backlinks 由 Search 内部组合成有界多跳。持久 EvidenceCard/evidence_group 和完整 SearchPlan 并非第一版必需。

## 外部 API

### Add

请求保持一期和官方二期调研中的形状：

```json
{
  "request_id": "run:sample:chunk:0",
  "messages": [
    {"role": "user", "timestamp": 1704067200000, "content": "原始消息"}
  ],
  "user_id": "run:sample",
  "session_id": "sample-session-0"
}
```

Add 的成功条件是：

- 请求体通过严格 schema 校验；
- 原始消息、幂等记录、工作缓存和最低可用的原文检索索引已经提交；
- 同一 `user_id` 下立即可以通过 Search 找回这些证据；
- 相同 `user_id + request_id + payload` 重放只返回原结果，不再次调用模型；
- 相同 request_id 携带不同 payload 返回明确冲突。

AM-Link 对一次 Add 的每个阶段只尝试一次，不在服务内部退避、重复请求模型、重复请求 embedding 或启动后台补偿。暂时失败直接返回明确的依赖错误，由比赛调用方按官方规则重试。外部重放同一 request_id 时，服务只补做之前未完成的阶段；已经成功提交的 raw event、索引和 mutation 不重复写入，也不重复计费。

成功响应只返回官方允许的三个 ID 和 `success=true`。参评增强模式下，若配置为必需的 reflection 或派生索引失败，Add 返回官方允许范围内的明确错误，并在内部状态和观测中标记 `incomplete`，等待调用方重放；显式 `raw` 实验模式只承诺原文和 FTS，不是 graph 故障后的降级，观测将 Reflection 记为 skipped。

### Search

请求保持：

```json
{
  "query": "用户想知道的内容",
  "options": ["可选的题目选项"],
  "user_id": "run:sample",
  "top_k": 100
}
```

响应仍然只有证据：

```json
{
  "data": [
    {
      "id": "memory:fact:...",
      "content": "带有时间、角色和来源的证据正文",
      "score": 0.87,
      "created_at": "2024-01-01T12:00:00Z"
    }
  ]
}
```

Search 不生成最终答案、不使用 gold/rubric、不跨 user_id，也不返回模型的选择理由或隐藏思维链。`content` 可以是可读的证据卡片，但必须来自已保存的 raw/ref 内容；不能把 query 重新写成答案。

Search 也不做内部错误重试。模型规划、embedding 或索引失败时返回明确错误，由官方调用方重试；0.1.0 不采用运行时故障降级。

## 内部对象不对外暴露

| 对象 | 作用 | 是否直接出现在比赛响应 |
| --- | --- | --- |
| `RawEvent` | 不可变原始消息和来源 | 通过证据正文间接出现 |
| `WorkingMemory` | 本段待整理原文、相关旧 refs 的工作视图和处理位置 | 否 |
| `MemoryItem` | 共用结构的 episode/person/entity/concept/event/fact 内容节点 | 通过证据正文间接出现 |
| `MemoryRef` | 指向 raw 或 memory 节点的稳定地址，与类型和显示名分离 | 以 result id 或正文来源出现 |
| `Mutation` | `gpt-4o-mini` 提出的受约束结构变更 | 否 |
| `SearchPlan` | 查询意图、候选来源、过滤和证据槽位 | 否 |
| `InspectView` | 从已知 ref 精确读取正文、来源和正向引用 | 否 |
| `Backlinks` | 查真实入边及候选预览，由 Search 编排后续读取 | 否 |
| `EvidenceCard` | fact 与必要 source 的可读组合 | 可以序列化为 result content |
| `NarrativeView` | 给模型看的自然语言片段和 speaker/时间上下文 | 否 |
| `StructuredSidecar` | 给校验器和模型作边界提示的 ref、状态、来源字段 | 否 |
| `Observation` | Add/Search 内部运行轨迹 | 只进入本地观测产物 |

内部 schema 变化不应破坏官方 Add/Search contract；需要新增对外字段时先以靶场适配器验证，不能把内部实验字段直接放入正式接口。
