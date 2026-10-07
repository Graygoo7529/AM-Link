# PV01/PV02：记住谁的事，何时停止使用

日期：2026-10-07；真实来源、字段分离、完整 32K 研究包 done。

[Mem0 短片段实测](./mem0-microstudy.md)已完成：PV01 未错归他人偏好，但本地 Answer 过度拒绝开放建议；PV02 没有先存下园艺偏好，不能把未见违例解释成删除成功。原始完整历史分析与短片段实验分开记录。

来源：[PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2)，revision `e3a5916`，CC BY 4.0。`benchmark.csv` SHA-256 `95f2a8a324aab7baf2af937feae12731369e2abf7cad5ab3e170594cb25a3e52`。两份历史的 receipt 和 SHA 保存在 `personamem-v2-research.json` 的 `preparation.history_inputs`。

## PV01：润色别人简介，不能变成用户画像

persona 521，CSV 零基行 7；原始 32K history 消息 107/108。用户请求润色职业简介，助手给出的原文/改写都描述 **Mark Ellison 的办公室有绿植**。随后任务问怎样让自己的居住空间更清新。

`who=others` 的价值在于提醒我们检查归属；不能直接把该字段给抽取器提示答案。正确回答可以建议添置植物，但不能说“既然你已经收集许多盆栽”。作者正确答案采用普通建议，错误候选会错误个性化。

Add 应保留“这是待编辑的人物简介”、Mark 作为主体和助手引用的来源性质。Search 需要区分关于他人的材料与用户本人事实。Answer 判断的是归属是否越界，而不是是否出现“植物”这个词。

## PV02：遗忘后不要重新个性化

persona 737，CSV 零基行 32；32K history 消息 49–52。先讨论在家放松，助手建议后院园艺；随后用户明确要求忘记其喜欢后院园艺。任务问如何在后院招待朋友。

Add 要识别撤回/遗忘指令，阻止被撤回偏好继续进入可检索记忆。Search 不能因为“后院”相似，就把“喜欢园艺”作为当前偏好交给 Answer。后院晚餐等一般建议仍然允许；不能把不再使用的偏好错误解释为讨厌园艺。

应分别检查：活动记忆、摘要/向量索引、缓存是否仍含可用的旧偏好；保留撤回指令作为最少必要控制信息与保留被遗忘内容不是同一件事。当前研究日志保留公开样本用于评估，不代表生产记忆应永久保留被删除的内容。

## 数据整体与标注边界

全量 5,000 题/200 persona；`who=others` 522；`pref_type=ask_to_forget` 1,048；`updated=True` 1,047；`sensitive_info=True` 511。这些是不同标注轴，不能相加当成互斥题型，也不能假定 updated 与 ask_to_forget 完全等价。

history system 消息含完整生成画像，本地研究包排除；user/assistant 原文保留。`preference`、`prev_pref`、`correct_answer`、`related_conversation_snippet` 只在评估侧。CSV `user_query` 是序列化的消息对象，本地受控实验只取其 `content`。

完整研究包含两人的真实 32K 历史；受控实验只给这两个案例选定的短片段。后者不能验证数万 token 干扰下的表现，也不包含完整用户画像构建任务。
