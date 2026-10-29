# AM-Link 可观测性标准接口 v1

2026-10-29新增：`reviewed independent node checkpoint`为真实store提交事件，记录committed_node_refs、group_complete=false和未推进的水位。不要把它算成整组完成；最终`reflection mutation commit`才包含完成组凭据。Add的maintenance另报groups_with_committed_nodes。向量index事件记录正文版本和片段范围；query.embedding/merge的lineage记录实际命中范围，模型可见范围仍以context实际输入凭据为准。合法关系菜单位置与支持说明在reflection输入/输出成对保留，不把位置数当图边数。

全局Select的投影带`view=contribution_summary`及`member_fragment_map`，网页显示“实际输入为贡献摘要”与绑定原文数量。贡献摘要不是新证据、不是全文阅读凭据；全局选中后仍携带局部已选原文范围。原文页、贡献摘要、最终展开分别记录，不能因为摘要没展示一句话就断言原句未在局部Select被读取。真实Answer诊断另记model/answer事件，计费统计须包含它们但不重复计数；它不属于AM-Link标准Search。

遗忘范围：`forget source scope`保存候选来源位置、选择说明及实际原文；`forget source correspondence`每条来源单独记录指令、原文和布尔判定/quote/理由，模型输入不包含选择器解释。阳性quote须是该来源的真实子串。来源选择不是已删除，拒绝项不进入屏蔽；协议错误仍使必要接收失败。`add atomic intake`的`retained_episode_refs`记录同事务内真正提交的未遗忘原文投影；旧episode只隐藏、不改写。需分别核对目标范围、无关原文是否仍有活动episode、以及最终Search是否泄露被删除信息。

状态：接口约定、Python recorder、校验器与研究视图接入已实现；Mem0 研究实验和 AM-Link 二期 0.2.0 均已接入 native 内部步骤观测，并保留真实模型切片档案。AM-Link 尚未部署或参加官方 Smoke。此接口是诊断侧接口，不改变比赛 Add/Search API。

靶场的 `ObservedTarget` 自动提供 API 根 span；native 工厂可通过 `set_observation_parent` 连接内部步骤。`Artifacts.text` 提供 `amlink.artifact.v1` 可显示正文，`amlink.note.v1` 将研究评注绑定到真实查询/步骤/哈希，详见 [接入与评注指南](./STUDIES.md)。两者是独立附属格式，不修改 observation v1 事件字段。

## 覆盖范围

| operation | 需要记录的可见事实 |
| --- | --- |
| add | 实际输入来源、逻辑 request_id、尝试次数、成功/错误、幂等命中或恢复 |
| extract | 原文来源 → 派生记忆的关联；实体/时间等产物由带哈希的 artifact 定位 |
| store / index | 成功写入的版本或快照引用；成功并不自动代表所有增强完成 |
| search | 原始 query 引用、最终返回结果及顺序、错误与耗时 |
| retrieve | 查询改写/扩展后的 query 引用、候选及检索分数、候选来源 |
| select | Query/Backlink 候选、实际 rank/score、是否选中和候选预算截断；不同方法分数不可直接横比 |
| context | 最终可见上下文 artifact，引用精确片段；被裁剪/排除的候选 selected=false |
| answer | 实际上下文 → 回答 artifact；模型版本记录在子 model span |
| eval | 回答 → 评估 artifact；指标/rubric、评估器版本和判定保存在 artifact |
| model | 每一次真实模型调用一个 span；token/费用若未提供则 null，失败尝试也记录 |

内部可见步骤是公开事件和产物来源关系，不收集或伪造模型隐藏思维链。原文、记忆、答案和评分文件留在本地 `data/`，事件只保存引用；不记录 Key、Authorization、连接密码或整段异常消息。

## JSONL 事件约定

每行是一个完成的 span，`schema_version=amlink.observation.v1`。精确字段和验证入口见 [`observability.py`](./observability.py) 的 `validate_event`。事件分为：

- 身份：run_id、dataset_pack_sha256、trace_id、span_id、parent_span_id、record_id、task_id、request_id。
- 阶段：operation、name、attempt（从 1 起）、replay（none/cached/resumed）。二期使用 `select` 表示模型对 Query/Backlink 候选 References 的筛选与排序，使用 `reflection` 表示工作区维护和 Mutation 工具循环；不另设 rerank。同逻辑请求重试 request_id 不变；每次尝试的 span_id 不同。
- 时间与结果：带时区 started_at/ended_at、单调时钟 duration_ms、status（ok/error/skipped）、error（code/retryable）。空结果是成功 Search 且 outputs/candidates 为空；依赖失败必须 error。
- 证据：inputs/outputs 引用；links 为 derived_from/retrieved_from/selected_from/supports/contradicts/supersedes；只能连接本 span 已声明的引用。
- 候选：candidates 的 ref_id、rank、score（可 null）、selected；rank 从 1 起，不重复。
- 模型：model 为 null，或仅在 model span 中提供 provider/name/input_tokens/output_tokens/cached_tokens/cost_usd/usage_source；不可在父子 span 重复记账。

每个引用包含 `id/kind/artifact/sha256/locator`：artifact 是相对于运行目录的 POSIX 路径，sha256 为文件字节哈希，locator 定位 JSON pointer、turn 或字符范围。kind 为 source/memory/query/result/context/answer/evaluation。引用 id 应在运行中稳定且唯一代表同一产物；若要在同一 span 原样透传，只在 inputs 声明一次并在 candidates 引用。

source artifact 应保留源 dataset/record/turn 与字符范围；派生 memory artifact 应保留版本、实体、时间解释和原文来源。Web 不自动读取这些路径，只展示来源引用，防止导出时意外混入任意文件。分析者可在本机按路径和哈希另行核对。

## Python 接口

```python
from pathlib import Path
from benchmark.observability import ObservationRecorder

with ObservationRecorder(
    Path("benchmark/data/runs/<run>/observability.jsonl"),
    run_id=run_id, dataset_pack_sha256=pack_digest,
) as recorder:
    with recorder.span("search", name="memory.search", record_id=record_id,
                       task_id=task_id, request_id=request_id) as search:
        with recorder.span("retrieve", name="hybrid.retrieve", parent=search,
                           record_id=record_id, task_id=task_id,
                           request_id=request_id) as retrieve:
            # 实际执行检索后，将真实 inputs / outputs / candidates 填入 retrieve。
            pass
```

Recorder 创建新文件，不覆盖旧实验；异常默认记录类型和 retryable=false，调用者可提前设置更准确的错误分类。它不会自动重试，也不替业务决定成功。成功幂等重放用 replay=cached，不能再创建未实际发生的 model span。

写入错误会显式抛出；若业务决定不让观测故障中断服务，必须另报 `observability_incomplete` 并将该次诊断标为不完整，不能伪装有完整轨迹。完成式日志遇到进程崩溃可能缺父 span；导入器报告孤立子 span，不能当作根流程成功。未来可扩展 start/end 双事件，但需升级版本。

## 与现有 benchmark 和 visualization 的连接

将文件放到同一个 run 目录后，`python -m visualization.build --local --run ... --run-kind experiment --web` 会自动读取。必须与该 run 的 pack digest、record/task 对齐；Search/Answer/Eval 根请求使用 benchmark 的 search_id，Add 使用实际 namespaced request_id。parent/child 必须处于同 trace、record、task、request，时间范围相容。完整图导入验证 span ID、引用一致性和父子关联；不会用墙钟顺序冒充并行执行因果。业务 user_id 应在本地运行配置中映射到 record_id；真实租户标识无需向展示层暴露。

没有孤立步骤只代表关联通过，不证明全部行为已采集。若采集方确认已拦截该次运行的所有模型调用，可另写 `observability.meta.json`，字段必须为 `schema_version="amlink.observation.v1"`、相同的 `run_id` 和 `dataset_pack_sha256`、`model_capture_complete=true`、非空 `producer` 版本。导入器还要求每次 API 请求都有关联的 Add/Search 根步骤；它不认证采集声明真实性。缺少声明、孤立步骤或未知费用时，不输出确定的全运行调用/费用总计。Recorder 不自动签发完整声明。

links 的方向固定为 `from_id` 指向 `to_id`：memory derived_from source，result retrieved_from memory，context selected_from result，evidence supports answer，new supersedes old；contradicts 表示尚未解决的冲突，不自动挑选较新值。候选 score 的算法、索引版本和过滤条件应存入被引用的产物，便于解释排序变化。产物存储及业务埋点由后续 AM-Link 实现负责。

页面按实际问题显示 Search 及其子步骤，并包含该问题之前的相关 Add 步骤。默认 API trace 与内部观测缺一方时明确标记缺失。Answer/Eval artifact 的正文不自动解释为结果；若希望并排显示回答与评价，使用 [`visualization/DESIGN.md`](../visualization/DESIGN.md) 中带来源的 observations 投影。

## 建议验收门槛

2026-10-23新增内部artifact（不扩展span顶层）：`format_version=1`的引用可见清单、`evidence disclosure receipt`、`reflection prefix policy`、证据组装箱。范围使用原文Unicode字符半开区间与正文digest；`call_returned`表示相同主决策输入已送出并成功返回，不代表模型理解。Select不会解除Inspect页面的回放保护。装箱同时保存冻结输入，供受限LLM离线对照；`packing_unit=evidence_group`需与旧单节点卡分开解释@k。网页最多展示20行范围/组决策，裁剪显示预览及完整artifact路径；旧数据缺字段保持未知。

1. 原文片段可以追到 Add、派生记忆、返回结果、最终上下文；缺一段报告断链。
2. 未记录用量是未知，实际零模型调用需在完整 trace 下计数确认；token/费用仅汇总 model span。
3. 错误、无结果、跳过、缓存重放可区分；失败尝试不会从耗时/费用中消失。
4. 引用完整性和传输成功与回答正确性分别报告；抽取内部不可见时不得自动归因。


## 2026-10-27 收敛链路观测（此前阶段）

沿用v1 span，无新顶层协议。`reflection local plan/group`记录v2原文范围、主归属与共享背景；`reflection program advance`是程序检查，`model_read_receipt=false`，不能计作模型已读。`statement source review`保存联合审查实际输入、修改/撤销、重审端点与保留提案的来源对应；审查分页的来源位置仍是全局表位置。`reviewed draft`区分commit与episode_only，原子组凭据保留完成理由；显式遗忘导致的空组为forgotten。

`query vector reused`、`unchanged body vectors reused`记录模型调用为0，只复用向量、不复用候选结果。Select的coverage绑定所选ref和fragment，非法辅助说明计入omitted；它是模型导航说明，不是事实证据。图探索context更新增加new_reference_refs/new_read_ranges，实际新增范围与语义增益分开；后者仍为unknown_requires_review。网页沿用产物预览显示这些内容，完整材料可回查。

## 2026-10-27 接收与整理分离（当前）

仍使用 v1 span/artifact。新增或调整的语义如下：

| 事件/产物 | 含义 |
| --- | --- |
| `add atomic intake` | 同一事务的 raw/episode/双索引/成功凭据，及必要遗忘；输出 committed 才说明提交完成 |
| `add receipt replay` | 已成功请求重放，模型调用为 0；不能推断 Reflection 已完成 |
| `add delivery outcome` | intake、reflection（buffered/completed/unfinished）、maintenance_error 和 progress；组完成/未完成、未分组消息、连续水位分开 |
| `reflection local plan/group` | v3 自然问题分组、逐组凭据；有完成缺口时水位不越过 |
| `resume local draft` | 版本核验后恢复同组草案；未完成不等于新请求失败 |
| `statement source review` | `uN` 对象绑定的合法修订、剩余事项；应用到草案不等于提交；替代依据需可核对原句 |
| `search exploration transaction` | 临时语境中的一次决策/读取/筛选，成功才合入；错误步骤不贡献证据 |
| `search partial completion` | 局部停止原因、丢弃本步、保留引用数量；子错误仍保留 |
| `search final pack` | completion/stop_reason 与实际结果；complete 指有界流程结束，不代表证据充分或答案正确 |
| `evidence packing decisions` | 已选范围、重复卡复用、预算遗漏、路径闭合及 omitted_edges；来源完整性失败显式抛错 |

网页在 Add 与 Search 摘要中显示这些状态以及内部错误步骤数。该数含嵌套 span，不是独立模型失败次数；模型尝试按 model span 单独计数。旧轨迹缺少字段时显示未知，不根据父级 HTTP 200 补推。中途观测写入失败仍不能声明采集完整。HTTP 默认不启用内部 recorder，native 靶场完整采集。


## 2026-10-28 工具交付与局部审查

标准事件仍为amlink.observation.v1。以下细节进入已有可显示artifact：

- 协议诊断format_version=1：layer（dependency/incomplete/protocol/business）、finish_reason、call_id/response_id、schema_fingerprint、字段/约束路径。公开错误不包含原文，私有轨迹可核对实际请求和返回；请求ID未报告时保持null。
- 调用协议format_version=1：实际max_completion_tokens、schema指纹及HTTP请求ID；模型span仍是一份真实尝试，用量缺失保持null。不要累加父/子error span当作额外模型调用。
- 局部审查format_version=2：round、committed=false、decisions的before/after/evidence_positions、source_receipts、issues/remaining_work。撤销依据不出现在持久支持中；recheck_required表示端点变化后必须重审。reviewed draft展示暂存而非完成凭据。
- 完成仍以reflection mutation commit和group receipt为准；Add 200只说明必要接收已提交。网页展示“本组局部审查（尚未提交）”，将撤销依据与写入支持分列；旧事件缺失的新字段不能推断为成功。

工具往返仅本轮离线对照，未进入生产，不生成虚构的跨请求对话/缓存成功事件。实际对照与完整历史质量门槛见本轮实施报告。

## 2026-10-28 来源约束与实际增量

`reflection mutation commit` 的可显示产物增加 `format_version=1 / committed=true / increment / no_item_change`。`increment.created` 是本次新 ref，`support_added` 是正文和时间均未变化的旧 ref，`navigation_updated` 是可变导航正文变化；每项记录 kind 和 added_source_refs。事务成功后才输出，不把临时提案或审查解释计入已写入记忆。空列表表示该类实际变化为零，旧产物缺字段则未知。网页在完整产物范围内显示“已提交的实际记忆增量（非草案）”。

contains 的 `contains_source_mismatch` / `reflection_contains_source_mismatch` 记录来源范围不合，不等于模型已做语义证明。节点模型输入的 `reuse_options` 只是当次实际读完且仍可见的旧对象提示；输出仍是完整统一节点条目，不生成额外模型调用或虚构阅读凭据。独立复用数组/简写是已撤回实验，仅存在历史源码快照和轨迹中。

## 2026-10-29 可见字段与增量审查

- `statement source review` 的units/decisions带 `review_task`；support_addition 的 `added_source_refs` 与 `source_positions`仅指新增支持候选。网页显示任务含义；审查撤销不是删除已有节点。
- 原有 `evidence disclosure receipt` 的披露片段保留kind和完整事件时间，叙事区别消息日期；字段反馈有item_changes和是否实际已读，未读时不暗取正文。
- `evidence packing decisions` 的 `visible_graph_refs` 是基于最后一次实际模型输入范围纳入的邻居正文；没有另一次Inspect不代表模型未见，标签或旧版本凭据不能合格。最终路径仍需来源闭合。
- 真实组件中的冻结Query/人工图必须标注，不把人工图算作Reflection成果；已选择反证、错误前提说明与正面事实分别人工核对，不以返回数量替代质量。
