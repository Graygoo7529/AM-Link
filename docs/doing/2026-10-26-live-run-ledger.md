# 2026-10-26 单一主链路真实实验台账

基线 `2490307`，本轮各迭代均使用真实 embedding 与 gpt-4o-mini；无内部重试。表中版本是独立实验，不是线上开关。标准完整报告与独立Select、中断分开。模型返回包括随后校验失败的响应，不能当成方法成功。

已落盘模型span共929次尝试，928次返回：embedding 246、gpt-4o-mini 682；1次provider_timeout。中断的per3最多另有1次在途请求未落盘，不把它记为零。token为已返回响应中报告的input_tokens 8,088,944、output_tokens 145,261，费用未核账，不推算金额。

覆盖5种数据来源、16个已完成Search的问题身份（case_id/search_id去重）；多次复验不是独立样本。查询扩展23次、Select84次、BFS决策195次、Reflection主决策333次、来源审查47次，均有真实模型响应。没有Answer调用。

| 运行 | Add成功/总数 | Search成功/总数 | 来源Recall@5 | 返回模型次数 | 节点/边 | 错误或条件 |
| --- | --- | --- | --- | --- | --- | --- |
| live26-r1-c2 | 1/4 | 1/1 | — | 25 | episode:4 / 0 | add:reflection_no_draft_progress:3 |
| live26-r1-l1 | 1/2 | 1/1 | 1.0 | 17 | episode:2 / 0 | add:reflection_patch_ambiguous:1 |
| live26-r1-lm4 | 0/0 | 0/1 | 0.0 | 0 | episode:4, fact:10 / 0 | search:provider_timeout:1 |
| live26-r10-conv41 | 1/2 | 1/1 | 1.0 | 21 | episode:2 / 0 | add:reflection_review_invalid:1 |
| live26-r10-per29-questions | 0/0 | 6/6 | 1.0 | 64 | episode:14, fact:3, person:1 / 3 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r11-c2 | 3/4 | 1/1 | — | 48 | episode:4, fact:10 / 2 | add:protected_workspace_budget:1 |
| live26-r12-conv41 | 2/2 | 1/1 | 1.0 | 17 | episode:2, fact:5 / 0 | 无API错误；不是语义质量保证 |
| live26-r2-p2 | 1/2 | 1/1 | 1.0 | 11 | episode:2 / 0 | add:reflection_no_draft_progress:1 |
| live26-r3-c2 | 1/4 | 1/1 | — | 29 | episode:4 / 0 | add:model_input_budget:1; add:reflection_no_draft_progress:1; add:reflection_review_quote_invalid:1 |
| live26-r3-conv44 | 0/0 | 1/1 | 1.0 | 14 | episode:2, event:1, fact:3, person:2 / 0 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r4-l1 | 1/2 | 1/1 | 1.0 | 20 | episode:2 / 0 | add:reflection_no_draft_progress:1 |
| live26-r5-c2 | 1/4 | 1/1 | — | 50 | episode:4, fact:5 / 1 | add:reflection_no_evidence_progress:1; add:reflection_relation_output_invalid:2 |
| live26-r5-lm4 | 0/0 | 1/1 | 0.5 | 6 | episode:4, fact:10 / 0 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r5-per29 | 1/14 | 1/1 | 1.0 | 80 | episode:14, event:5, person:1 / 5 | add:reflection_item_draft_invalid:1; add:reflection_no_draft_progress:6; add:reflection_no_evidence_progress:2; add:reflection_review_incomplete:3; add:reflection_review_invalid:1 |
| live26-r6-l1 | 2/2 | 1/1 | 0.5 | 22 | episode:2, event:3, person:2 / 4 | 无API错误；不是语义质量保证 |
| live26-r6-lm4 | 0/0 | 1/1 | 0.5 | 9 | episode:4, fact:10 / 0 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r7-conv30 | 1/1 | 1/1 | 1.0 | 8 | episode:1 / 0 | 无API错误；不是语义质量保证 |
| live26-r7-conv30-common | 2/2 | 1/1 | 1.0 | 24 | episode:2, event:2 / 0 | 无API错误；不是语义质量保证 |
| live26-r7-conv41-common | 1/2 | 1/1 | 1.0 | 19 | episode:2 / 0 | add:reflection_no_evidence_progress:1 |
| live26-r7-lm4 | 0/0 | 1/1 | 0.5 | 17 | episode:4, fact:10 / 0 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r8-c2 | 1/4 | 1/1 | — | 44 | episode:4, fact:3 / 2 | add:reflection_no_evidence_progress:1; add:reflection_relation_output_invalid:1; add:reflection_tool_budget:1 |
| live26-r8-l1 | 0/0 | 1/1 | 0.5 | 14 | episode:2, event:3, person:2 / 4 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r8-lm4 | 0/0 | 1/1 | 0.5 | 8 | episode:4, fact:10 / 0 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-r8-per29 | 5/14 | 1/1 | 1.0 | 119 | episode:14, fact:3, person:1 / 3 | add:mutation_unknown_source:2; add:reflection_material_budget:1; add:reflection_no_query_progress:3; add:reflection_tool_budget:3 |
| live26-r8-per3 | — | — | — | 125 | episode:14, fact:11, person:1 / 11 | 主动中断旧版本；125次已返回；非完整报告 |
| live26-r9-b2 | 1/2 | 1/1 | — | 10 | episode:2 / 0 | add:reflection_no_evidence_progress:1 |
| live26-r9-c2 | 3/4 | 1/1 | — | 66 | episode:4, fact:8 / 1 | add:reflection_tool_budget:1 |
| live26-r9-conv41-common | 2/2 | 1/1 | 1.0 | 23 | episode:3, person:2 / 0 | 无API错误；不是语义质量保证 |
| live26-r9-l1 | 0/0 | 1/1 | 1.0 | 13 | episode:2, event:3, person:2 / 4 | 冻结库Search；继承库的Add质量见来源运行 |
| live26-select-assess | — | — | — | 1 |  / — | 冻结候选独立Select；不计Add/Search成功率 |
| live26-select-needs | — | — | — | 1 |  / — | 冻结候选独立Select；不计Add/Search成功率 |
| live26-select-order | — | — | — | 1 |  / — | 冻结候选独立Select；不计Add/Search成功率 |
| live26-select-passages | — | — | — | 1 |  / — | 冻结候选独立Select；不计Add/Search成功率 |
| live26-select-readable | — | — | — | 1 |  / — | 冻结候选独立Select；不计Add/Search成功率 |

## 版本与范围

- r1–r4：试验局部草案、来源逐条审查；patch无进展、引文抄写和输入预算失败均保留。
- r5–r7：改来源位置表与问题优先序列化；完整人物29的r5为1/14 Add，整引用Select仍遗漏头盔。
- r8：独立原文卡Select与直接局部审查；LM4三项金额进入最终原文；完整人物29仍5/14 Add。人物3停止时有14个最低episode、11fact、1person、11边，不能当成完整成功。
- r9：实际可见待办约束、别名归并自环去重、图导航数量；L1首次观察到一次Backlink补齐原籍。C2仍有正文与来源待办不一致。
- r10：选中片段不再缩成520字符；先节点审查后关系审查，更新端点；conv41暴露关系工具仍允许revise的问题。新增6题Search采用此版。
- r11：待办与missing_material统一，修正冲突来源页入口与保护；C2为3/4 Add，失败从反复Inspect转为protected_workspace_budget，未彻底解决。
- r12：关系review工具只允许keep/drop，节点review支持校正已有时间字段，来源保留时间/角色；conv41为2/2 Add、来源2/2，撤销1条错误supersedes。最终代码为此版主方法，无默认关闭开关；随后仅同步首部repair为实际投影待办，并通过本地回归，不将这项末轮提示修改冒充新的真实整库结果。

辅助窗口：L1、P2、B2及conv30/41/44依赖作者标注周边选择，只用于定位，不代表完整历史准确率。完整记录：C2文档、PerLTQA人物29与人物3；冻结库：LM4与L1，以及人物29六题。六题虽选择完整记录任务，来源库存在失败Add，run的空Add报告不能替代源库5/14事实。

## 本地复核

每个live26-*档案位于忽略的benchmark/data/runs/。report.json记录API与来源指标，observability.jsonl和artifacts记录模型实际输入/输出。amlink-method.json和完成运行的method-source-snapshot.json记录实际源码；部分外壳system-version仍含r3/r4/r8旧标签，不能用该显示名称替代源码哈希。Search副本另有method.json记录来源库与哈希。per3中断有interruption.json，不能补写成功report。

五个独立Select比较有diagnostic.json及标准模型span：readable、assess、order、passages、needs。没有逐候选评估/需求规划分支留在服务中。早期网络权限拒绝以及一次数据文件路径错误未执行模型，未计入模型span。

详见[实施报告](./2026-10-26-live-method-implementation.md)与[案例解释](../../casestudies/2026-10-26-live-method-cases.md)。
