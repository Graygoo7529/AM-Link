# LoCoMo 回放

## 数据可得性结论

赛事官网说明 Smoke 使用“固定小子集”，正式评测还包含不开放的私有数据；公开评测代码仓库也明确说明 datasets、service addresses、credentials、databases 和 run artifacts 不在公开发布中。因此当前不能从赛事仓库下载官方 Smoke 文件，不能把自造样例当作官方成绩。

LoCoMo 是可复现的替代基线。原作者仓库公开 `data/locomo10.json`，包含 10 段长对话、按 session 排序的对话 turn，以及带 `question`、`category`、`evidence` 的 QA 标注。原始数据采用 CC BY-NC 4.0；自评数据只放在本机临时目录，不进入本项目提交包。

来源：

- 赛事说明：[Agent Memory Challenge](https://agentmemories.ai/competition/)
- 赛事公开评测代码：[AML-memory/agent-memory-leaderboard README](https://raw.githubusercontent.com/AML-memory/agent-memory-leaderboard/main/README.md)
- LoCoMo 原作者仓库：[snap-research/locomo](https://github.com/snap-research/locomo)
- LoCoMo 原始数据：[locomo10.json](https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json)
- LoCoMo 数据许可：[LICENSE.txt](https://raw.githubusercontent.com/snap-research/locomo/main/LICENSE.txt)

## 转换方式

```powershell
.\.venv\Scripts\python.exe -m aml_memory.locomo `
  B:\tmp\locomo10.json `
  B:\tmp\locomo-balanced.json `
  --qa-per-category 10
```

转换器的约束与处理：

- 每个 session 按 20 条消息切 Add，符合赛事公开运行参数；不跨 session 拼接；session 时间转为毫秒并写入每条消息。
- `speaker_a` 映射为 `user`，另一位 speaker 映射为 `assistant`；文本之外的 BLIP 图片 caption 以 `[Image: ...]` 保留。
- QA 的 `evidence` 被解析为 `D<session>:<turn>`，映射回原始 turn 文本作为 `contains_any` target，不使用答案文本伪造证据。
- LoCoMo 少量原始标注含多个 ID 粘连、前导零或不存在的 ID；转换器只保留可解析且确实存在的证据，题目没有有效证据时跳过，并有回归测试。
- category 映射为 `single_hop`、`temporal`、`multi_hop`、`open_domain`、`adversarial`；这些是 LoCoMo 自评标签，不等同于赛事最终评分类别。

## Lexical HTTP 基线

环境：Python 3.13、真实 Uvicorn、`AML_LLM_ENABLED=false`、`AML_EMBEDDING_ENABLED=false`、隔离 SQLite。样本为全部 10 段对话，每类最多 10 题。

| 指标 | 结果 |
| --- | ---: |
| Add / Search | 399 / 480 |
| Add / Search success | 1.0 / 1.0 |
| Add latency p50 / p95 | 21.243 / 27.202 ms |
| Search latency p50 / p95 | 21.926 / 28.905 ms |
| evidence recall@1 / @5 / @10 | 0.108736 / 0.279083 / 0.366417 |
| MRR | 0.235646 |
| duplicate rate | 0.0 |
| temporal recall@10 | 0.5675 |
| single-hop recall@10 | 0.118705 |
| multi-hop recall@10 | 0.196998 |
| multi-hop chain coverage@10 | 0.1375 |
| open-domain recall@10 | 0.41 |
| adversarial recall@10 | 0.505 |

这只是证据召回基线，不是 LoCoMo 的 Answer/Judge 分数，更不是赛事成绩。结果显示 temporal/open-domain 受到词面帮助较大，single-hop 和多跳链明显较弱；后续优化应优先检查 query planner 的同义改写、entity/concept 图扩展和多证据去重。

## 扩大 lexical 基线：3 个 conversation

为减少单个 conversation 的偶然性，进一步选取 `conv-26`、`conv-30` 和 `conv-41`，保留完整 session、每类最多 10 题，共 101 个 Add、138 个 Search。生成命令：

```powershell
.\.venv\Scripts\python.exe -m aml_memory.locomo `
  B:\tmp\locomo10.json `
  B:\tmp\locomo-3samples-full.json `
  --sample-limit 3 --qa-per-category 10 --top-k 10
```

在隔离真实 Uvicorn 服务上完成回放，所有请求 HTTP 200：

| 指标 | 结果 |
| --- | ---: |
| Add / Search | 101 / 138 |
| Add latency p50 / p95 | 21.378 / 26.799 ms |
| Search latency p50 / p95 | 14.208 / 20.132 ms |
| evidence recall@1 / @5 / @10 | 0.154589 / 0.278019 / 0.409058 |
| MRR | 0.250963 |
| duplicate rate | 0.0 |
| temporal recall@10 | 0.666667 |
| single-hop recall@10 | 0.131667 |
| multi-hop recall@10 | 0.083333 |
| multi-hop chain coverage@10 | 0.0 |
| open-domain recall@10 | 0.366667 |
| adversarial recall@10 | 0.666667 |

按目标证据数拆分，multi-hop 为 18 个问题、34 个目标，仅 3 个目标进入 Top-10；single-hop 为 30 个问题、74 个目标，命中 11 个。temporal 和 adversarial 各 30 个问题，Top-10 目标召回均约 0.677。这个分布支持优先实施“路径完整性重排”和“查询谓词/实体扩展”，不建议先单独增加 embedding 权重。报告：`B:\tmp\locomo-3samples-lexical-report.json`。

## 查询词过滤回放

在相同 manifest、相同 `top_k=10` 和全新 SQLite 上启用高置信英文问句停用词过滤，并保留 GraphPath/source-event 折叠代码：

| 指标 | 旧 lexical | 当前实现 | 变化 |
| --- | ---: | ---: | ---: |
| evidence recall@1 | 0.154589 | 0.161836 | +0.007247 |
| evidence recall@5 | 0.278019 | 0.405435 | +0.127416 |
| evidence recall@10 | 0.409058 | 0.508696 | +0.099638 |
| MRR | 0.250963 | 0.299209 | +0.048246 |
| temporal recall@10 | 0.666667 | 0.800000 | +0.133333 |
| single-hop recall@10 | 0.131667 | 0.190000 | +0.058333 |
| multi-hop recall@10 | 0.083333 | 0.194444 | +0.111111 |
| multi-hop chain coverage@10 | 0.000000 | 0.111111 | +0.111111 |
| open-domain recall@10 | 0.366667 | 0.500000 | +0.133333 |
| adversarial recall@10 | 0.666667 | 0.733333 | +0.066666 |
| Search p95 | 19.554 ms | 19.770 ms | +0.216 ms |

当前实现的 101 Add / 138 Search 仍全部 HTTP 200，duplicate rate 为 0。由于该 lexical 回放没有 LLM 生成的 memory links，以上提升主要来自查询词过滤；GraphPath 的收益尚需带结构化 links 的更大回放验证，不能把本表全部归因于图路径重排。报告：`B:\tmp\locomo-3samples-stopword-report.json`。

## Embedding 状态

已用真实 `embedding-3` 做最小协议探针，HTTP 200、512 维返回正常；隔离 TestClient Add 也完成向量写入。早期一次 28-chunk HTTP 回放的 Uvicorn 进程没有获准访问外部网络，因而全部进入 `ProviderError` 降级、没有写入向量。该结果是运行环境错误，不是智谱限流或 embedding 质量结果。

在允许出站网络的全新隔离数据库上，下面的局部 embedding-3 对照已经成功；按用户要求不再运行全量 LoCoMo。

## 局部真实 Add/Search 对照

为了观察单个案例而不是等待全量 LoCoMo，选取 `conv-26` 的前 4 个 session，仅保留 single-hop、temporal、multi-hop 各 2 题，共 5 个 Add chunk、6 个 Search。生成命令：

```powershell
.\.venv\Scripts\python.exe -m aml_memory.locomo `
  B:\tmp\locomo10.json `
  B:\tmp\locomo-local-4sessions.json `
  --sample-limit 1 --session-limit 4 `
  --categories 1,2,3 --qa-per-category 2 --top-k 10
```

同一 manifest 分别在真实 Uvicorn 服务上运行：

| 模式 | Add / Search | 成功率 | evidence recall@10 | MRR | single-hop@10 | multi-hop@10 | chain coverage@10 | Search p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lexical | 5 / 6 | 1.0 / 1.0 | 0.333 | 0.250 | 0.000 | 0.500 | 0.500 | 7.5 ms |
| `embedding-3` | 5 / 6 | 1.0 / 1.0 | 0.250 | 0.222 | 0.000 | 0.250 | 0.000 | 131.5 ms |
| `gpt-5.4-mini` debug + `embedding-3` | 5 / 6 | 1.0 / 1.0 | 0.417 | 0.417 | 0.500 | 0.250 | 0.000 | 8,934.8 ms |
| `gpt-4o-mini` + `embedding-3` | 5 / 6 | 1.0 / 1.0 | 0.667 | 0.479 | 1.000 | 0.500 | 0.000 | 5,924.6 ms |

这里的 embedding-only、完整调试链和正式模型链均在允许出站网络的隔离进程中运行。正式模型链使用智增增 `gpt-4o-mini` 和智谱 `embedding-3`：Add p50 为 7,506.5 ms、p95 为 23,503.0 ms；Search p95 为 11,545.6 ms。最终数据库包含 `daily=76`、`fact=9`、`entity=3`、`concept=21`、55 条 typed links 和 114 个 512 维向量；累计索引文本数为 121，稳定节点的后续向量会替换早期版本。

正式模型链的 5 次 Add 和 6 次 Search 均返回 HTTP 200，5 次 maintenance 中 4 次直接完成、1 次因不可稳定复现的 `ValueError` 降级；后续 Add 已批量处理 watermark 后事件，最终 maintenance backlog 为 0。失败输入单独重放时 schema、source ordinal 和 memory reference 均合法。该现象不影响 raw/FTS 可检索性，但在并发压测前仍需统计更大样本的 maintenance failure rate。

正式模型链 provider 计数为 `llm_maintenance=5`、`llm_search=6`、`embedding_context=5`、`embedding_search=6`、`embedding_index=5`，与设计调用边界一致。相较同一切片 lexical，Recall@10 提升 `+0.333`，single-hop 从 `0` 提升到 `1.0`；multi-hop chain coverage 仍为 `0`，说明当前改进主要来自结构化事实、planner 和混合召回，尚不能单独归因于 links。

逐题 target rank（按 manifest 顺序）如下：

| 问题类别 | lexical | embedding-3 | debug full |
| --- | --- | --- | --- |
| temporal: LGBTQ support group | `[2]` | `[1]` | `[1]` |
| temporal: Melanie paint sunrise | `[null]` | `[null]` | `[null]` |
| multi-hop: education fields | `[null,null]` | `[null,null]` | `[null,null]` |
| single-hop: Caroline research | `[null]` | `[null]` | `[2]` |
| single-hop: Caroline identity | `[null]` | `[null]` | `[null]` |
| multi-hop: counseling support | `[1,6]` | `[3,null]` | `[1,null]` |

局部结果说明：

1. 结构化调试链对 single-hop 有明显帮助，`Caroline research` 从未进入 top-10 提升到第 2；
2. 仅 embedding 没有提升该切片，说明向量相似度不能替代事实结构和查询意图；
3. multi-hop 仍经常只召回链中的一条证据，当前主要短板是跨 fact 的关系扩展和链完整性，而不是 Add 协议；
4. 调试链每次 Search 大约 9 秒、Add 中位约 18 秒，远高于 lexical；正式 Full 前必须依赖赛事要求的模型、并发和 1,200 秒请求上限重新校准；
5. Search 结果仍可能同时出现 fact 摘要、raw turn 和 entity 派生证据，后续要按 canonical/evidence group 做更强的派生节点折叠，同时保留 raw source 可追溯性。

报告文件（本机临时目录）：

- `B:\tmp\locomo-balanced.json`
- `B:\tmp\locomo-balanced-report.json`
- `B:\tmp\locomo-sample-report.json`
- `B:\tmp\locomo-local-lexical-report.json`
- `B:\tmp\locomo-local-embedding-net-report.json`
- `B:\tmp\locomo-local-full-debug-report.json`

## v0.3.0 扩大回放

### 全部 10 conversation 的确定性回放

在当前 lexical 降级链路上，对相同 399 Add / 480 Search manifest 使用两套全新 SQLite 独立回放。两次所有请求均为 HTTP 200，480 个查询的结果 ID/顺序差异为 0：

| 指标 | 旧 10-conversation 基线 | v0.3.0 A | v0.3.0 B |
| --- | ---: | ---: | ---: |
| Recall@1 | 0.108736 | 0.150869 | 0.150869 |
| Recall@5 | 0.279083 | 0.359918 | 0.359918 |
| Recall@10 | 0.366417 | 0.439438 | 0.439438 |
| MRR | 0.235646 | 0.292152 | 0.292152 |
| duplicate rate | 0.0 | 0.0 | 0.0 |
| Search p95 | 28.905 ms | 30.829 ms | 30.829 ms |

相对旧基线，Recall@10 绝对提升 `0.073021`，MRR 绝对提升 `0.056506`。改进来自查询词过滤、稳定同分排序和当前融合逻辑；该回放没有结构化 provider 生成的 links，不能用于证明 links 的单独收益。

### 正式 provider 的 2-conversation 切片

选取 `conv-26`、`conv-30` 的前 4 个 session，每类保留少量 QA，共 10 Add / 18 Search，`top_k=100`：

| 指标 | lexical | `gpt-4o-mini + embedding-3` |
| --- | ---: | ---: |
| Recall@1 | 0.282407 | 0.421296 |
| Recall@5 | 0.550926 | 0.578704 |
| Recall@10 | 0.592593 | 0.662037 |
| MRR | 0.506635 | 0.618546 |
| multi-hop Recall@10 | 0.5 | 0.5 |
| chain coverage@10 | 0.5 | 0.0 |
| Search p95 | 12.646 ms | 14,001.413 ms |

完整增强链路所有请求成功，无 warning；数据库包含 153 daily、12 fact、3 entity、8 concept、46 links、176 vectors，10 个 maintenance/enrichment job 全部 completed。结构化事实通常能排在前列，但对应的多条 raw source 未必同时进入前十；随后进行的真实 provider 互补 evidence group 选择 A/B 反而使 Recall/MRR 和 multi-hop chain coverage 回退，因此该实验已删除，当前保持 evidence group 去重和 source 伴随召回。

同一存储上的 planner 重跑受上游模型输出波动影响，因此表中完整链路可用于确认可用性和总体效果，不能把小样本的每项变化严格归因为某一个重排特征。完整故障和并发结果见 [扩大验证与可靠性优化](./扩大验证与可靠性优化.md)。
