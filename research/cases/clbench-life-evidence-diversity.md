# C01：社区讨论综述——证据覆盖与排除条件

日期：2026-10-05；真实样本获取、pack 和方法分析 `done`；目标系统未运行。

来源：[CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life)，Tencent Hunyuan / Fudan；evaluation-only 许可。行 API `train` offset 100、length 2 的第 1 条，任务 ID `a760132c-d3bc-2931-f3e5-db24be64d0b8`，类别 Communication & Social Interactions / Community Interactions。

本地 `dataset/data/snapshots/clbench-life/train-100-2.jsonl`，SHA-256 `60e6a7b099aafc4bb9d4c09bb09571b2d3878e3750821e1010cd1dbbd0aa2cc3`。这是 HF 无截断缓存快照，未固定上游 revision。

## 原始任务与准备

原始用户消息前半是社区帖及评论，`<|TASK|>` 后是任务。题目要求仅依据评论比较 iPhone / Android 的总体倾向、判断是否有明确胜者、归纳三个主要观点并各引三句，再在五种立场的表格中各给三句，所有引文不能重复，也不能使用原帖。

读取器以明确分隔符拆开背景和任务。背景进入历史，问题进任务，rubrics 仅留评估侧。新增两行共形成 7 条历史消息与 2 个任务；这是消息数量，不是评论数量。内容中的产品说法是数据内观点，不是本项目对现实产品的事实背书。

## 参考记忆处理

Add 要保留评论者、评论/回复边界、原帖身份、原文及立场上下文。重复的页面 UI 文案可以作为有来源的派生清理，但不能丢失否定、引用对象和回复关系。

Search 除相关性外还要考虑立场覆盖，排除原帖，避免同一观点或引文重复占满预算。题目最终要求 24 个互不重复的引文位置（3×3＋5×3）；单纯取最相似的几段无法保证覆盖。参考方法可以按子需求召回并汇总，保留每个引文的出处。

Answer 才负责概括总体倾向、组织表格和引用。没有检查完整评论前不能预先断言哪一平台获胜；模型看到的检索片段分布也不能自动当作全体评论比例。

## 可检验假设

比较单一相似度排序与有覆盖约束的检索，在同一上下文预算下检查：原帖是否误入、观点是否缺失、引文是否重复、是否有来源、最终是否满足 rubric。数据没有直接可用的 gold turn evidence，不能将 rubric 当召回标签。
