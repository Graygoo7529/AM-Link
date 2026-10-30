# 最新模型规则与智增增 text-embedding-v4 核验

核验日期：2026-10-28。代码基线 `9a91259`。本轮为规则、调用兼容性和切换方案核验；未修改方法默认模型、运行配置或旧数据库，未部署。

后续用户确认后，已完成默认迁移与新库验证，见[实施记录](./2026-10-28-embedding-v4-migration.md)。下文保留确认前的探测事实与建议，不代表当前仍未切换。

## 规则已明确

[官方用户文档](https://agentmemoryleaderboard.ai/zh-cn/docs#doc-modes)及[赛事问答第 5 项](https://agentmemoryleaderboard.ai/competition/)现在共同说明：开源方法榜使用 `text-embedding-v4` 做 embedding、`gpt-4o-mini` 做 LLM 相关组件，reranker 不限制。数据库、索引和内部架构不限制；Search 仍交付证据，Answer/Eval 由平台执行。

此前 9 月调研中“embedding 不限制、Search 模型尚不明确”已过时。当前 `embedding-3` 的本地结果仍是有效研究记录，但不是新规则下参评模型组合的验证。现有 Query 扩展、Select、Reflection/BFS 等 LLM 组件已使用 gpt-4o-mini，不需因这条规则更换。

指定 docs 页面通过普通 HTTPS 读取返回 200；浏览搜索工具不能直接打开该页面，另从可读取的官方赛事问答交叉核对。没有借用旧网页文案替代新要求。

## 智增增实测可调用

从忽略的私有配置读取已有智增增 Key，只在探测进程中使用；目标为 `https://api.zhizengzeng.com/v1/embeddings`。直接调用 AM-Link 当前 `Providers.embed()`，没有 SDK/内部重试，也没有发送数据集或用户历史。输入为蓝色笔记本的中英合成短句。

| 探测 | 结果 | 耗时 | 输入 tokens |
| --- | --- | --- | --- |
| GET `/v1/models` | 200；889 个模型 ID 中没有列出 text-embedding-v4 | 0.464 秒 | 不适用 |
| text-embedding-v4，2 条，512 维 | 200；两条 512 维向量，索引 0/1，数值有限非零 | 0.472 秒 | 15 |
| text-embedding-v4，10 条，1024 维 | 200；十条 1024 维向量，索引 0–9，数值有限非零 | 0.854 秒 | 115 |

两次 response 的 `model` 均为 `text-embedding-v4`，当前解析、维度检查和归一化均通过。**模型列表未列出不等于不能调用。** 本轮共 2 次 embedding 请求、130 输入 tokens；实际账单未知，没有测持续吞吐或长文本质量。代理返回模型名不能独立证明底层模型身份，参评仍应保存模型声明与调用记录。

请求和响应标准模型 span、脱敏结果与官方页面快照位于忽略的 `amlink/data/diagnostics/embedding-v4-20261028/`。Key 不进入脚本、正文或报告。

## AM-Link 如何切换

当前调用已是兼容 `/embeddings`，发送 `model/input/dimensions`，读取 `data[index, embedding]`；短文本场景无需重写调用器。建议下一轮正式切换统一采用 1024 维（模型默认维度），512 维也已实测支持；本轮未比较它们的召回质量。

```dotenv
AML2_EMBEDDING_ENABLED=true
AML2_EMBEDDING_BASE_URL=https://api.zhizengzeng.com/v1
AML2_EMBEDDING_MODEL=text-embedding-v4
AML2_EMBEDDING_DIMENSIONS=1024
AML2_EMBEDDING_BATCH=10
AML2_EMBEDDING_API_KEY=<从现有智增增私有配置读取>
AML2_DB_PATH=amlink/data/memory-v4.sqlite3
```

LLM 继续使用原 gpt-4o-mini 配置。这里的 embedding Key 是智增增 Key，不能继续传智谱 Key；现有 Config 不会自动把 LLM Key 借给 embedding，必须显式提供。此块是迁移示例，不是可原样使用的已配置凭据文件。

需配套处理三处：

1. **批量上限**：阿里云[同步接口文档](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)规定 v4 一批最多 10 条；当前默认 `embedding_batch=32`。引擎已按配置分批，切成 10 即可；建议配置层再拒绝 v4 的超限批量，防止漏配。
2. **单条长度**：同一文档规定每条最多 8192 tokens；当前预算主要按字符，Add 会把完整最小 episode 一次嵌入。字符预算不等于 token 上限。正式迁移需检查长输入，并设计超限时保真分段索引；不能悄悄截断原文、切回旧模型或只修改维度校验来假装成功。本轮短句成功不覆盖这个问题。
3. **向量空间与实验身份**：模型/服务地址/维度进入 `embedding_fingerprint`。新配置打开旧 embedding-3 库会被 `index_configuration_mismatch` 拒绝，这是正确行为。按项目约定使用新库重新 Add，再 Search；保留旧档案，不能修改 meta 绕过检查。实验脚本也要改用智增增 embedding Key，并记录新模型/维度，历史脚本中的 ZHIPU_KEY 绑定不能照搬。

正式切换的验收顺序：默认配置与模型约束 → 短输入及 10/11 条分批检查 → 长 episode 边界 → 新库 Add/Search → 相同公开切片的证据覆盖与成本对照。维度增加使向量存储与点积计算量约增加一倍，但不直接决定 provider token 计费或召回收益。

本轮文档修正与接口探测 done；默认切换、长文本索引改造及新模型完整方法实验未实施。无数据库删除/迁移、无归档变更、无代码或配置变更。
