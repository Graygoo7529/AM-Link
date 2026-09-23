# 模型接入经验

本次只归档配置，未重新发起付费模型调用。下面是一期最后使用的接口；Key 在本地被忽略的 `docs/private/phase1-server.env`，取回于 2026-09-23。历史调用成功不等于今日余额、授权或模型仍可用。

| 用途 | 提供方与模型 | 地址 | 环境变量 |
| --- | --- | --- | --- |
| LLM | 智增增代理，`gpt-4o-mini` | `https://api.zhizengzeng.com/v1/chat/completions` | `OPENAI_BASE_URL=https://api.zhizengzeng.com/v1`，`OPENAI_API_KEY` |
| 向量 | 智谱，`embedding-3` | `https://open.bigmodel.cn/api/paas/v4/embeddings` | `ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4`，`ZHIPU_API_KEY` |

一期使用 HTTPX 直接发送兼容请求，不使用 pi SDK，也不要求安装 OpenAI SDK。两种模型分别启用：`AML_LLM_ENABLED=true`、`AML_EMBEDDING_ENABLED=true`；`AML_ENRICHMENT_MODE=sync`。配置模板在 [归档 .env.example](../../archive/phase-1/.env.example)，模板和旧默认值不是二期推荐值。

LLM 使用 Bearer 鉴权，发送 model/messages、温度 0 和 JSON 对象输出要求；结构化整理和查询计划采用不同提示。响应仍要做结构、来源与用户范围校验，JSON 模式不能保证业务正确。旧代理曾返回错误层级或 null 字段，等价空值可规范化，未知非空字段应拒绝。

Embedding 请求包含模型、文本数组和 512 维参数，读取向量后检查条数、维度并归一化。一期批次上限配置为 64，长文本分块后索引。模型或维度改变需要重建；只换同一模型的 Key 通常无需重建，但应先在自造文本上比较响应维度和向量一致性。

一次 Add 可能调用语义上下文检索、LLM 结构化整理和多个向量批次；一次 Search 可能做查询向量、LLM 计划和扩展查询向量。它们并非一比一调用。历史恢复任务还可能只重算 embedding，因此不能以两家控制台计数不同判断 LLM 未接入。

## 验证与配置经验

1. 用不含正式数据的最小请求检查 HTTP 状态、返回模型标识、结构与 embedding 维度。代理自报模型名不能独立证明底层模型身份，正式参评需满足主办方审核要求。
2. 用全新测试用户做 Add/Search，检查实际结构化记录、索引完成状态、命中证据及每阶段模型开销；复用相同请求可能命中缓存，不能拿来测真实 Add 延迟。
3. 区分“尝试计数”“成功请求”“tokens/账单”。保留脱敏 request ID、模型和时间用于供应商排查，不记录 Key 或正式请求正文。
4. Key 在进程启动时读入，改配置后需要重启。2026-08-08 已换过 embedding Key，旧 Key 已停用；后续只读取本地私有快照，不从旧聊天复制旧值。
5. 一期最后的并发配置为 LLM 8、embedding 16；provider HTTP 最多重试 2 次，后台任务总尝试 1 次。二期不要照抄这些重试配置，先按官方错误约定实现请求内失败退出。

二期的接入优先复用“薄适配、独立配置、真实小样本验证”。是否继续使用这些模型及代理，取决于[二期规则核验](../phase-2/integration-research.md)和容量实测。
