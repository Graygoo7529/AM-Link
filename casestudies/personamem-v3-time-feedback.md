# V301/V302：时间切面、反馈与记忆寿命

日期：2026-10-07；samples 全量结构统计、两个按时间遮罩的研究包 done；未复现原版 backend 评估器。

来源：[PersonaMem-v3](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3)，本地 samples 的 profiles/context/queries 三表。revision 与 SHA 由各 receipt 保存；pack 另记录 queries 和 context 文件 SHA。CC BY-NC 4.0。下文是来源的中文转述。

## V301：看过的相似内容，为什么不是推荐第一名

persona 36，query `36:0017:recsys_2026-04-05_a2`，2026-04-05 11:00 UTC。任务给出 16 个候选，作者答案把候选 15 放首位；候选 13/3/6 是 hard negatives。

其 2,232 条事件里，只有 **600 条严格早于提问**；其余 1,632 条不能写进这次历史。标注明确候选 15 的 held-out 正反馈发生在提问后 1 小时，它是评估目标，不能回填为已知偏好。

历史 `event-325716` 是 “Five HP, Pure Panic” 的停留行为，`event-684397` 是观看 “Last Bullet, Last Laugh” 超过 75%；两条均早于 query，已绑定为页面原文摘录。后者对应候选 6，但在此题是重复/近似的 hard negative。因此“曾互动”“负面偏好”“这次不宜重复推荐”是不同语义，不能把所有 hard negatives 都解释成用户讨厌。

Add 保存事件、动作、时间、内容身份与可见反馈；Search 获取相关偏好和近期接触/排除信息；Answer 根据候选生成排序。未来正反馈是离线推荐的标签，不保证仅凭历史就能唯一推导完整 golden 排序。此题标注区分首选与 hard negatives；本地研究保留这个区别，尚未运行原版评分器。

## V302：继续帮我计划，但不要长期记住

persona 68，query `68:0142:pshift_68_005_chatbot`。2026-04-06 06:59 的 `event-987393` 包含东京/京都行程讨论；独立 `user_message` 又明确表示不要记住日本旅行部分，但继续帮忙做计划。4 月 11 日询问日本与本地旅行如何权衡。

本条限制同时出现在 `conversation_json` 和独立 `user_message` 中，不能声称只读前者就一定漏掉它。研究 reader 仍保留独立字段，避免未经逐条核验就假设所有记录都重复。真正的难点是 Add 把当前任务帮助和长期偏好保存分开；Search 可以满足当前明确的行程问题，但不能把旧旅行兴趣当作持续有效画像。作者标注是短期偏好过期，无替代立场；预期回答比较 PTO、费用、时差和休息需求。

这条 query 前有 2,228 条可见事件、127 条同刻或未来事件被排除。标注的精确失效时间属于评估信息，不能偷偷交给 Add；可观察的用户限制是独立证据。

## 特别容易泄漏的字段

- `persona_profiles`、`preferences`、`preference_details` 和 `preference_evolution` 包含生成/归纳标签，部分 evolution 提及事件之后的强化记录和 lifetime 次数。
- `conversation_json` 内部还含 `embeds_pref_idx`；不能只清理 CSV 顶层字段。当前投影逐条只保留 role/content。
- `interaction_type` 是作者交互分类，只用于结构统计；研究包保留原始 action 与内容，不把 implicit_negative 等分类直接写成用户态度。
- `supporting_history`、`groundtruth_preference`、`golden_response`、`rubrics`、`judge_prompt` 均留在评估侧。
- 提问时间与事件时间使用同一秒级时间轴比较；pack 统一转成毫秒，保留原始文本时间。当前使用严格 `<`，同刻事件暂不进入历史。

全量事件是 221,817 条，其中作者标记 implicit_negative 160,853；这包括动作的隐式信号，不代表 160,853 次明确拒绝。应保留 action 原值和推断置信度，避免把“跳过”直接升级为永久厌恶。
