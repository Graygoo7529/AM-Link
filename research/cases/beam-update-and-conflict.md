# B01/B02：正常更新与未解决冲突不能混为一谈

日期：2026-10-05；真实源核对、pack 构建与方法分析 `done`；目标系统未运行。

## 来源与准备

[BEAM 作者数据](https://huggingface.co/datasets/Mohammadta/BEAM)，CC BY-SA 4.0，作者 Mohammad Tavakoli 等。行 API `100K` split 的 offset 1、length 1，`conversation_id=2`。本地 `dataset/data/snapshots/beam/100K-1-1.jsonl`，SHA-256 `798be0bbc8c866375cb6dffac6f2ef0a5f55623379be2c86be0be36d2d256f4c`；这是无截断的缓存快照，没有宣称固定上游 revision。

原始记录含生成背景、计划、chat、probes。只有 chat 进入历史；原文代码也作为聊天内容保留。新 pack `dataset/data/prepared/beam-update-cases.json` 有 3 批历史、200 条发言、20 道题（十类各 2 题）；背景画像、理想答案、rubric、source_chat_ids 只留在标注侧。

## B01：每日配额从 1,000 更新到 1,200

任务 `knowledge_update:0` 问应用中 API Key 的每日调用配额。以下为历史中文转述，不是现实 OpenWeather 产品规格。

| 原文位置 | 片段与含义 |
| --- | --- |
| chat 第一批，源 id=32；pack turn `0:32` | 用户要求处理每分钟 60 次、每天 1,000 次限制，并提到 2024-03-10 取得 Key。 |
| 同批，源 id=66；pack turn `0:66` | 用户明确说新的每日配额是 1,200，要求代码反映这次更新。 |
| 作者答案 | 每天 1,200 次。 |

Add 保存同一项目、同一 Key 配额属性的旧值、新值、出现顺序和来源；新值是明确更新，可标记旧状态被取代。Search 问“当前”时优先返回 id=66，必要时附 id=32 解释变化；问“最初”时返回旧值。不能拿每分钟 60 次回答每日配额，也不能把代码中后续重复出现的 1,200 当作多次独立事实确认。

可检验假设：有状态更新关系的检索比单纯按文本相似度排序更少返回旧值。需要实际运行后才能量化。

## B02：“已有 Key”与“从未取得 Key”

任务 `contradiction_resolution:0` 问是否已取得该项目的 API Key。源 id=32 明确提到已经取得；源 id=70（pack `0:70`）又称从未取得。作者标注还引用 id=34、36 作为先前使用背景。

这是对同一经历的冲突，不等于“旧 Key 已失效”“换了项目”或“新状态没有 Key”；原文没有提供这些解释。参考 Add 保留互相冲突的陈述及来源，标为待澄清，不能自行改成一个一致故事。Search 返回冲突两端，Answer 应说明前后不一致并请求澄清；这与 B01 接受明确配额更新的策略不同。

`source_chat_ids` 为作者提供的候选线索；本轮人工核对上述关键原文，当前通用 BEAM reader 尚未把这些不同形状的线索转换成全面验证的 gold turn evidence。因此现有 benchmark 仍将这些任务标为 ungraded，不声称已实现 BEAM 证据召回评分。

## 经验

“新消息覆盖旧消息”不是通用正确方法。应区分明确更新、限定场景差异、否定、纠错和不可解释矛盾。作者标注可辅助诊断，但 Add 不能读取它。
