# 2026-10-14 真实模型链路补充实验

这份记录回答一个具体问题：案例有没有真正经过 Mem0 或 AM-Link 的 Add、Search 和 Answer？如果没有，断点在哪里？本轮使用同一批经过案例绑定的本地切片，分别调用 Mem0 2.2.1 和当前 AM-Link 0.2.1。Mem0 使用 `gpt-4o-mini` + `embedding-3`；AM-Link 使用相同的模型组合；AM-Link 的 Answer 另用 `gpt-4o-mini` 对保存的 Search 结果做独立诊断。所有调用均关闭 SDK 内部重试，运行产物保存在被忽略的 `benchmark/data/runs/`，没有把凭据写入报告。

这些是研究靶场的受控切片，不是官方排行榜分数。Answer 只读取系统实际返回的 Search 证据，不读取数据集标注；人工比较时才使用案例的参考答案和 evidence plan。因此，“Answer 正确”只表示这一次输入和这一次模型调用得到的结果符合案例要求，不能外推系统总体准确率。

## 运行清单

| 案例 | Mem0 Add/Search/Answer | AM-Link Add/Search/Answer | 主要结论 |
| --- | --- | --- | --- |
| B03 顺序与五项约束 | Add 7/37；Search 1/1；正式运行因 Add setup 未完成而跳过 Answer，后验 Answer 仍列出五个相似但错误的主题 | Add 10/37；Search 1/1；Answer 运行成功但五项顺序全部偏离标注 | 长历史首先在 Add/Reflection 丢批，随后 Search 只保留相似主题，没保住顺序槽位 |
| LM03 猫名/仓鼠拒答 | 1/1；1/1；Answer 正确拒答 | 1/1；1/1；Answer 正确拒答 | 相关实体被召回不等于目标实体存在；两套系统都能完成边界拒答 |
| P01 人物关系方向 | 9/9；5/5；Answer 答出张小红的兄弟是张小明 | 9/9；5/5；Answer 答出张小明是弟弟 | 短关系链上，结构化方向和原文来源能够帮助回答 |
| P02 到达事件/关系冲突 | 运行完成；Answer 给出“已经到达” | 运行完成；Answer 保留到达时间和地点 | 需要继续人工核对原文与标注口径；不能把流畅答案当成冲突已解决 |
| M01 三跳关系拒答 | 5/5；Answer 明确说 Dickens 配偶国籍没有证据 | 5/5；Answer 同样拒答，并标出 Darwin/Amala Paul 是无关冲突 | 多跳检索能找到无关冲突，Answer 仍需保持主体边界 |
| C02 税务条件分解 | 2/2；Answer 给出常见分类，但补充了题目未给出的条件 | 2/2；Answer 还加入 punitive damages、pain and suffering 等未出现在证据中的项目 | 主要断点在 Answer 的条件推理，不是 Add/Search 是否成功 |
| PV03/PV04 敏感信息与遗忘 | Add 8/15；Search 1/2；正式运行无 Answer；后验 Answer 对 housewarming 问题明确说证据不足 | Add 0/15；Search 2/2；独立 Answer 只给通用建议 | “没有复述敏感信息”不能证明底层没有保存；AM-Link 的严格 Reflection 校验先阻断了评估 |
| V31 时间切片/推荐装箱 | Add/Search/Answer 完成；Answer 给出三条游戏/幽默候选 | Add/Search/Answer 完成；Answer 只看到并推荐两条候选 | 最终装箱范围直接改变推荐覆盖；此切片无统一 gold，不作准确率判断 |

模型调用确实发生在链路中，而不是只读旧结果：AM-Link 关系组记录 26 次 `embedding-3` 和 28 次 `gpt-4o-mini` 模型 span，LM03 记录 2 次 embedding 和 3 次 LLM，B03 记录 136 次 embedding 和 269 次 LLM，PersonaMem 记录 47 次 embedding 和 46 次 LLM。Mem0 关系组记录 23 次 embedding 和 14 次 LLM，LM03 记录 3 次 embedding 和 2 次 LLM，B03 记录 17 次 embedding 和 7 次 LLM，PersonaMem 记录 18 次 embedding 和 8 次 LLM。计数来自各运行目录的 `observability.jsonl`，不是根据 Add/Search 请求数推算。

运行目录为：`mem0-report-b3-20261014-net`、`mem0-report-lm3-20261014-net`、`mem0-report-relations-20261014-net`、`mem0-report-persona-20261014-net`，以及对应的 `amlink-report-b3-20261014`、`amlink-report-lm3-20261014`、`amlink-report-relations-20261014`、`amlink-report-persona-20261014`。AM-Link 的独立 Answer 目录分别是 `answer-gpt4o-mini-b3-20261014`、`answer-gpt4o-mini-lm3-20261014`、`answer-gpt4o-mini-relations-20261014`、`answer-gpt4o-mini-persona-20261014`；Mem0 的 B03 和 PersonaMem 另有 `answer-posthoc-gpt4o-mini-*`，明确标记为 Add setup 未完成后的后验回答。

### B03：顺序题的两个断点

B03 的问题要求按出现顺序列出五个关注点：防抖、慢响应、快速输入、下拉/错误处理、监听器清理。Mem0 把 200 轮历史切成 37 次 Add，但只有 7 次成功；其余主要是 SDK 适配器的运行错误或模型错误。因为运行器要求先确认 Add setup 完整，正式运行跳过了 Answer；随后对同一个成功 Search 的结果做了后验 Answer，模型列出“防抖、慢响应、特殊字符、输入/错误区域、async/await”五个相似主题，仍没有恢复标注顺序。这里的正式链路缺失发生在写入阶段，后验 Answer 又显示 Search 证据集合本身已经不完整。

AM-Link 的 37 次 Add 中 10 次成功，25 次因为 `forget_requires_explicit_new_user_instruction` 被拒绝，另有模型工具输出和 mutation 错误。Search 仍返回了五个带来源的事实，内容分别偏向性能优化、API 错误处理、加载动画、定制实现和输入校验。独立 Answer 忠实地把这五条排成列表，但它们并不是案例标注的五个阶段。证据已经进入 Search，问题在于历史讨论的顺序没有成为可检索、可约束的结构，且失败 Add 使关键阶段根本没有进入记忆。

### LM03：一个成功的拒答基线

唯一原文说的是“猫叫 Luna”，问题问“仓鼠叫什么”。Mem0 和 AM-Link 都完成 Add/Search，Search 返回猫名，Answer 都明确说没有仓鼠姓名。这是一个重要的正例：系统没有因为“宠物 + 名字”的相似度而把 Luna 改成仓鼠名。它也说明拒答需要看到相关但不同的实体，不能把空结果简单等同于正确拒答。

### P01、P02：关系方向和原文冲突

P01 是短、清楚的关系题。Mem0 给出“张小红的兄弟是张小明”，AM-Link 还保留了“弟弟”的方向性描述。这个差异与 References 是否同时带有关系叙事和来源有关：只给两个名字很容易丢掉主语和箭头。

P02 的价值在于原文、时间和评估标签并不完全一致。两套系统都能产生一个流畅的“已经到达”答案，但这不等于已经解决冲突；后续应把原文日期、相对时间表达和标注答案并列展示，检查 Answer 是否主动说明口径，而不是只记录最后一句话。

### M01：检索到冲突，不代表冲突属于目标

问题要求沿“作品 → 作者 → 配偶 → 国籍”查找。两套系统都返回了与 Dickens、Darwin 和 Amala Paul 有关的材料。Mem0 和 AM-Link 的 Answer 都指出 Dickens 配偶国籍在证据中不存在，AM-Link 额外明确标出 Darwin/Amala Paul 的冲突与目标无关。这个结果支持一个观察：BFS 或相似度扩展可能把无关冲突带进语境，最终仍需主体、关系类型和来源一起约束答案。

### C02：证据齐全仍会在 Answer 断开

两套系统都完成了写入和检索，拿到了每月 500 美元、13% 损失扶养和 2,000 美元利息等材料。但 Mem0 依据常见规则补写一般损害的适用条件，AM-Link 还谈到题目证据中没有出现的 punitive damages 和 pain and suffering。这里没有明显的 Search 漏召回；模型看到了材料，却把“未知条件”改成了常见法律分类。理论链路需要在 Answer 前明确区分“证据说了什么”和“规则需要什么条件”。

### PV03/PV04：协议阻断和敏感信息边界

PersonaMem 长历史共有 15 次 Add。Mem0 成功 8 次，失败 7 次，两个 Search 中一个失败；由于 Add setup 不完整，运行器没有自动 Answer。AM-Link 15 次 Add 全部返回失败，其中 10 次是 `forget_requires_explicit_new_user_instruction`，其余涉及最小 episode 不可变、重复引用、schema、未知来源和 Reflection 不完整。Search 仍能返回两个查询的结果，独立 Answer 给出了通用理赔清单和安全传输建议，没有复述问题中的敏感标识。

这不能被解释成“AM-Link 已经完成遗忘”或“Mem0 没有保存敏感信息”。Mem0 的正式运行没有 Answer，但对成功 Search 的 housewarming 问题做后验 Answer 时明确说证据不足；这只能说明当时五条证据里没有可用的礼物偏好。AM-Link 的 Search 仍能给通用保险和礼物建议。更需要修复的是：本次 AM-Link 运行在 Add 返回失败的同时，数据库仍留下了 raw/node/edge，后续 Search 因而能够看到部分内容；这说明失败事务与可见状态之间还存在边界问题，不能让失败请求产生半提交记忆。下一步应把“敏感字段是否进入 raw、episode、向量、关系、装箱”作为单独的可观测判定，并在失败路径检查事务回滚。

### V31：装箱范围改变回答覆盖

该切片的 Add/Search/Answer 都成功，但没有统一 gold answer。Mem0 的 Answer 从证据中列出三条游戏或幽默相关候选；AM-Link 的 Search/装箱只交付两条，因此 Answer 只推荐两条。这个差异不是模型“会不会推荐”的抽象问题，而是最终装箱到底交付了多少候选、每个候选是否带完整来源的问题。它与当前 AM-Link 对旧检索分数重排、结果字符预算和证据去重的设计直接相关。

## 可复用的判断方法

以后页面和报告对每个案例都应按同一顺序展示：

1. **Add 是否完整**：成功数、失败数和第一类错误；若未完成，不把 Search/Answer 的缺失写成“模型答错”。
2. **Search 是否拿到目标证据**：看原始结果、结构化节点、关系扩展、Select 和最终装箱；若有 gold，只在此处使用 gold 做召回诊断。
3. **Answer 是否越过证据**：检查是否漏掉顺序、分母、日期、关系方向，或补写证据没有给出的常识和条件。
4. **结论边界**：把“这次模型调用答对了”与“这个方法在该类数据上有效”分开；后者需要更多同条件样本和重复实验。

本轮的直接改进方向是：为长历史 Add 提供批次完成度和失败水位；让顺序题的 episode 带稳定 ordinal/sequence 证据；让 Select/装箱保留问题要求的槽位和来源；在 Answer 提示中强制区分证据、缺失条件和模型推断；对敏感信息记录全链路的保存/过滤状态。
