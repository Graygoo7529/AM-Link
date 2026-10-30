# 2026-10-26 真实运行台账

共20个研究目录：16个完整Add/Search或Search-only运行，2个独立Select调用，2个调用模型前退出的脚本目录。涵盖9个不同问题、4类数据来源；不同代码版本和辅助窗口混合，仅作机制诊断。

标准观测捕获416次模型返回（embedding 109、gpt-4o-mini 307），其中Reflection 183、BFS 102、查询扩展12、Select 10。另两个独立Select诊断已知调用2次：1次返回、1次超时，但脚本遗漏Observer.bind，没有模型span及用量。合计418次已知请求尝试、417次有返回；不得把独立诊断伪造成完整观测。

标准观测累计输入3,415,695 tokens、输出100,622 tokens；两个独立诊断用量未知，因此这不是完整总tokens。供应商价格未核验，费用未知。全部运行无内部重试，每个完整运行上限200次请求/500万输入字符。

| run id | 模型返回 | Add成功/总数 | Search成功/总数 | 来源@1 / @5 | 边 | 错误 | engine源码SHA前12位 |
| --- | ---: | --- | --- | --- | ---: | --- | --- |
| evidence26-final-conv44-default | 0 | — | — | — / — | — | 旧档案名称有误；调用模型前退出 | — |
| evidence26-final-conv44-default-v2 | 13 | 0/0 | 1/1 | 1.0 / 1.0 | 0 | — | e15dce5e88ce |
| evidence26-final-lm4-default | 8 | 0/0 | 1/1 | 0.25 / 0.5 | 0 | — | e15dce5e88ce |
| evidence26-r1-lm4-default | 8 | 0/0 | 1/1 | 0.25 / 0.25 | 0 | — | c3ca89502ffc |
| evidence26-r2-lm4-select | 13 | 0/0 | 1/1 | 0.25 / 0.5 | 0 | — | 186ec86a5053 |
| evidence26-r3-c2 | 65 | 1/4 | 1/1 | — / — | 0 | add:reflection_tool_budget×3 | f5e2bae8885a |
| evidence26-r3-l1 | 31 | 1/2 | 1/1 | 0.5 / 1.0 | 0 | add:reflection_tool_budget×1 | f5e2bae8885a |
| evidence26-r3-p2 | 25 | 1/2 | 1/1 | 1.0 / 1.0 | 0 | add:reflection_tool_budget×1 | f5e2bae8885a |
| evidence26-r4-c2 | 56 | 1/4 | 1/1 | — / — | 0 | add:reflection_material_budget×1；add:reflection_no_draft_progress×1；add:reflection_relation_output_invalid×1 | 19d6ac3d382d |
| evidence26-r4-conv43 | 13 | 2/3 | 1/1 | 0.333333 / 0.666667 | 1 | add:reflection_no_draft_progress×1 | 19d6ac3d382d |
| evidence26-r4-conv49 | 14 | 1/1 | 1/1 | 1.0 / 1.0 | 0 | — | 19d6ac3d382d |
| evidence26-r4-l1 | 17 | 1/2 | 1/1 | 0.5 / 1.0 | 0 | add:reflection_relation_output_invalid×1 | 19d6ac3d382d |
| evidence26-r5-conv48 | 13 | 1/1 | 1/1 | 1.0 / 1.0 | 0 | — | bb519adf11b0 |
| evidence26-r5-l1 | 19 | 2/2 | 1/1 | 1.0 / 1.0 | 3 | — | bb519adf11b0 |
| evidence26-r5-per24 | 76 | 5/14 | 1/1 | 1.0 / 1.0 | 13 | add:mutation_unknown_source×3；add:reflection_item_draft_invalid×1；add:reflection_no_draft_progress×1；add:reflection_no_evidence_progress×3；add:reflection_relation_output_invalid×1 | bb519adf11b0 |
| evidence26-r6-c2 | 30 | 1/4 | 1/1 | — / — | 0 | add:reflection_no_draft_progress×3 | e15dce5e88ce |
| evidence26-r6-p2 | 15 | 2/2 | 1/1 | 0.0 / 1.0 | 0 | — | e15dce5e88ce |
| evidence26-select-readable | 0 | — | — | — / — | — | 观测构造参数缺失；调用模型前退出 | — |
| evidence26-select-readable-concise | 0 | — | — | — / — | — | provider_timeout；未采span | — |
| evidence26-select-readable-v2 | 1（未采span） | — | — | — / — | — | — | — |

16个运行的Search均有返回，但不能据此认为Add均成功或证据充分；尤其完整PerLTQA人物Add5/14。旧库副本的Add为0/0，必须回看来源运行的Add状态。@k是来源匹配指标，不是Answer准确率。3种金额是人工后验检查，未进入方法选择规则。

原文、模型轨迹、数据快照、SQLite及方法源码快照留在忽略的benchmark/data/runs/。独立Select缺失观测的限制另存diagnostic.json，未补造trace。当前代码的测试与结论见[实施报告](2026-10-26-evidence-and-draft-implementation.md)。
