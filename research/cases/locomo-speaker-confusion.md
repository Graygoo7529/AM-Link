# L03：谁的收养计划——人物归属与错误前提

日期：2026-10-05；源核对与方法分析 `done`，记忆系统实验未运行。

## 来源与定位

- [SNAP LoCoMo](https://github.com/snap-research/locomo)，`dataset/data/raw/locomo/locomo10.json`。
- SHA-256：`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`。
- `conv-26 / qa[153]`（`qa-153`），类别 5 adversarial；来源引用 `D2:8`。Maharana 等，ACL 2024，CC BY-NC 4.0。

## 原始材料与任务

2023-05-25，Caroline 说自己正在研究收养机构，希望给需要帮助的孩子一个家（中文转述）。题目却问：Melanie 夏天在收养方面有什么计划？

源字段 `adversarial_answer=researching adoption agencies` 是诱导的错误答案，不是应写入记忆的事实，也不是正确答案。这里的 evidence 引用是制造人物错配的相关片段，不能简单解释为“支持题目答案的证据”。

## 准备与记忆处理

Add 保留 `speaker=Caroline`、来源 `D2:8`、会话时间及完整陈述。`user_id` 隔离的是历史空间，不能代替空间内的说话者与实体归属。LoCoMo 将两位参与者映射为协议 user/assistant 时，也必须保留原始人名。

Search 可以返回该片段作为澄清上下文，但必须明确它属于 Caroline；它不能支持 Melanie 有同样计划。回答者应指出证据不足或说明人物错配，不能把两个人的经历合并。

“问题不可回答”不意味着 Search 必须返回空集。返回能纠正错误前提的上下文也可能有价值；是否充分需要结合 Answer 检查。

## 方法经验与检验

- 主题相关、字面命中、甚至命中作者列出的 evidence，都不等于能够支持问题。
- 对抗题的证据命中率不能直接当作“回答质量越高”的指标；原版与不含类别 5 的本地 Refined 版应分别报告。
- 可检验假设：固定召回内容，比较保留/丢失 speaker 对误归属率的影响；记录能否识别主体差异、是否错误复述诱导答案。
- 不凭单个相关片段宣称整个历史不存在任何信息；完整回答判断应以约定的可见历史为范围。
