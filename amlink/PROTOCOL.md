# AM-Link 二期协议边界草案

状态：设计初稿。本文把比赛外部协议和内部方法对象分开，避免内部结构泄露为未获官方批准的 API 扩展。

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

成功响应只返回官方允许的三个 ID 和 `success=true`。参评增强模式下，若配置为必需的 reflection 或派生索引失败，Add 返回官方允许范围内的明确错误，并在内部状态和观测中标记 `incomplete`，等待调用方重放；本地 lexical 基线可以在 raw/FTS 已提交时返回降级成功，但必须在观测中标记 `degraded`，不能声称结构化增强完成。

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

Search 也不做内部错误重试。模型规划、embedding 或索引服务失败时，只能使用本次请求中已经准备好的确定性候选和预先定义的降级路径；如果没有合法降级结果，就返回明确的暂时失败，由官方调用方重试。

## 内部对象不对外暴露

| 对象 | 作用 | 是否直接出现在比赛响应 |
| --- | --- | --- |
| `RawEvent` | 不可变原始消息和来源 | 通过证据正文间接出现 |
| `WorkingMemory` | 连续会话中的热缓存和待整理线索 | 否 |
| `MemoryRef` | daily/entity/concept/fact/evidence 的稳定引用 | 以 result id 或正文来源出现 |
| `Mutation` | `gpt-4o-mini` 提出的受约束结构变更 | 否 |
| `SearchPlan` | 查询意图、候选来源、过滤和证据槽位 | 否 |
| `InspectView` | 从已知 ref 展开正文、直接链接和反链 | 否 |
| `EvidenceCard` | fact 与必要 source 的可读组合 | 可以序列化为 result content |
| `Observation` | Add/Search 内部运行轨迹 | 只进入本地观测产物 |

内部 schema 变化不应破坏官方 Add/Search contract；需要新增对外字段时先以靶场适配器验证，不能把内部实验字段直接放入正式接口。
