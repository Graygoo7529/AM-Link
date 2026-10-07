# 数据地图：原始材料、准备结果与能力边界

本页保留 2026-10-05 案例分析时的样本范围。**2026-10-07 已补齐多项完整文件和 PersonaMem-v2 配套历史**；最新取得状态见[下载清单](./downloads.md)和[获取核验记录](../docs/doing/2026-10-07-huggingface-retry.md)，请勿将下表旧下载缺口当作当前状态。以下能力分析仍可参考；它们不是官方 AML 冻结包或系统评测结论。

| 数据源 | 本机材料 | 原始特点 | 当前处理结果 | 适合检查 / 边界 |
| --- | --- | --- | --- | --- |
| [LoCoMo 原版](https://github.com/snap-research/locomo) | 10 对话、272 会话、5,882 发言、1,986 题 | 双人跨会话经历，speaker/time/QA evidence；含图像 caption | 完整 pack 1,984 题，排除 2 个不存在的来源引用；保留发言来源和人物 | 时间、多跳、人物归属。对抗题 evidence 可是诱导片段；图片本体不在本机 |
| [LoCoMo-Refined 社区版](https://github.com/mem-eval-suite/LoCoMo_refined) | 10 对话、1,382 题 | 与本机原版对话完全相同，题目/答案有修改，无类别 5 | 已有六题 smoke pack，原始全文件可用 | 答案精度与完整性；不是独立历史，不应当成无泄漏的测试集 |
| [PerLTQA 中文](https://github.com/Elvin-Yiming-Du/PerLTQA) | 完整中文双文件；141 人物档案，32 人物有 8,593 题 | 作者生成的资料、关系、事件和对话，已经是结构化记忆 | 32 人物、160 分区、2,211 来源单元、8,593 题；全部引用可解析；另有两人案例包 | 中文关系与来源融合；不等于从零聊天建忆。存在源矛盾，不能只依赖标准答案 |
| [CL-bench](https://huggingface.co/datasets/tencent/CL-bench) | 3 / 1,899 条 | 新知识、规则、流程、任务和 rubric | 1 条多轮可构造环境；2 条单轮缺可靠边界，保留原输入 | 学习材料后办事；无直接 gold turn evidence |
| [CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life) | 5 / 405 条：原 3 条＋offset 100 起 2 条 | 比赛日志、社区讨论、信息碎片；messages/rubrics | 5 条均能拆历史和任务；新两条共 7 条历史消息、2 任务 | 引用准确、覆盖不同观点、遵守排除条件；五条不是代表性随机样本 |
| [BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) | `100K` 档 2 / 20 条历史，共 388 发言、40 probes | 长对话夹杂代码和多种记忆能力；生成背景与真实 chat 并列 | 新第二条完整 3 批、200 发言、20 probes；只 chat 进历史 | 更新、矛盾、长期指令。部分题有 source_chat_ids，但通用 evidence 映射仍未实现 |
| [ScriptMem](https://github.com/memorax-ai/ScriptMem) | 457 题，无真实剧本 | 多人物事件与关系题；单选、多选、排序 | 任务 pack 可用；缺历史明确标记 | 只能分析题型；不能把题目或合成 schema 示例写成历史 |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | 3 题，同 persona 521；缺对应历史 | 隐式偏好、当前问题、32K/128K 历史引用与评估答案 | 任务和标注分离；拒绝缺历史回放 | 可分析个性化任务。确认相对 history 路径属于 HF 数据仓库，不是当前 GitHub 代码仓库；HF 文件仍 502 |
| [LongMemEval S/M/Oracle](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | 来源公开；本轮仍未下载成功 | 历史会话、日期、问题、has_answer；Oracle 只保留答案会话 | 已有读取器，仍只通过合成结构测试 | 更新、时间、拒答。Oracle 不可冒充 S/M 的完整长历史难度 |

PerLTQA 的“来源单元”和 LoCoMo 的“发言”、BEAM 的“历史”不是同一统计单位，不能直接比较数量来判断难度或效果。所有派生 pack 仍保留原始材料，只做投影与分离；没有执行模型摘要或自动修复原始事实。

## 新查到但未取得可用样本的候选

| 候选 | 能力价值 | 已核对与本轮限制 |
| --- | --- | --- |
| [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) / [数据卡](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench) | 准确检索、从示例学习、长程理解、冲突解决；一个 context 对多个问题 | 官方 splits 已确认，CR/TTL 各一条 row 请求读取超时；没有保存不完整样本。已登记来源，未实现 pack reader。数据卡 MIT，复用子数据仍需跟踪来源 |
| [PersonaMem-v3](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3) / [作者代码](https://github.com/bowen-upenn/PersonaMem-v3) | 跨平台活动、正负反馈、用户意图与遗忘请求 | 已确认 context/profiles/queries 三类配置；数据卡继承 CC BY-NC 4.0。本轮仅调研，没有下载或适配。作者代码与数据卡的人物数量文案不同，未强行统一 |

## 使用顺序与比较方式

1. LoCoMo 用来建立可追溯的时间、关系和证据链对照。
2. PerLTQA 用中文案例检验结构读取、关系方向与源数据质量；结构化输入应单列实验组。
3. BEAM 用来区分更新、矛盾和长历史干扰；同一问题可在增量检查点重新问，但当前 plan 是全部 Add 完成后 Search。
4. CL-bench/Life 用来检验“带材料完成工作”。需补统一 Answer 和来源专用 rubric judge，不能只用字面召回排名。
5. 完整补齐 PersonaMem、LongMemEval 或新候选后，再扩展能力面；不因下载失败而拿 gold 标签伪造历史。

实验至少记录原始输入、pack/plan 版本、实际 Add/Search、来源映射、可见回答上下文、Answer/Eval 和实际调用费用。人工挑选的案例用于解释机制，不能外推成全量效果。
