# AM-Link 二期协议

## Add

`POST /v1/memory/add` 接受 `request_id`、`user_id`、`session_id` 和一个或多个带
`role`/`content`/可选 `timestamp` 的消息。请求先以原文形式持久化并按
`(user_id, request_id)` 幂等。只有 RawEvent、episode、词法索引以及开启时的
episode 向量全部完成，才返回成功响应。Reflection 是否触发不改变成功 Add 的
接口形状；尚未整理的内容仍通过 episode 可被后续 Search 检索。

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

## 错误与重试

无内部重试、后台补偿或模型故障降级。幂等成功重放不再次调用模型；未完成请求
可在官方重放时继续必要阶段。模型、embedding、索引和结构校验失败分别保留明确
错误，不能把空结果或部分完成伪装为成功。
