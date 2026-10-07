# 数据地图：原始材料、准备结果与能力边界

更新：2026-10-07。下载完整、可解析、已适配和完成评测是四种不同状态。[获取记录](../docs/doing/2026-10-07-huggingface-retry.md)、[研究记录](../docs/doing/2026-10-07-dataset-research.md)和[下载清单](./downloads.md)可追溯实际范围。这些材料不等于官方 AML 冻结包。

| 数据源 | 实际原始材料与标注 | 当前处理 | 用途与限制 |
| --- | --- | --- | --- |
| [LoCoMo](https://github.com/snap-research/locomo) | 10 对话、272 会话、5,882 发言、1,986 QA；speaker/time/evidence/caption | 完整 pack 1,984 题；排除 2 个不存在的来源引用 | 跨会话、时间、人物归属；图片本体未取得，对抗题 evidence 可能是诱导片段 |
| [LoCoMo-Refined](https://github.com/mem-eval-suite/LoCoMo_refined) | 10 对话、1,382 QA；与本机原版历史相同、题目修改 | 全文件可用，保留独立来源身份 | 检查答案精度；不能当成独立历史留出集 |
| [PerLTQA 中文](https://github.com/Elvin-Yiming-Du/PerLTQA) | 141 人物档案，32 人有 8,593 题；结构化资料、关系、事件、对话 | 32 人、160 分区、2,211 来源单元、8,593 题；引用均可解析 | 中文关系融合；已经是生成的结构化记忆，部分源与答案矛盾 |
| [LongMemEval](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | S/M/Oracle 全部取得，同一批 500 题，30 拒答；日期、has_answer、6 类题型 | 三题研究包保留完整 S 历史；日期解析已修复；全 S 做本地 BM25 | 更新、时间、拒答、多证据；Oracle 是答案会话筛选，不能代替长历史难度 |
| [CL-bench](https://huggingface.co/datasets/tencent/CL-bench) | 1,899 任务、500 context 分组；4 类/18 子类，31,607 rubric 条目 | 现有规则可拆 621 条，1,278 条未认证边界；不强拆 | 学习新规则并办事；rubric 不是证据位置；evaluation-only |
| [CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life) | 405 任务、3 类/9 子类，5,348 rubric 条目 | 405 条可按现有规则拆；保留已有案例包 | 工作材料覆盖、引用、排除条件；可拆不等于完成原版评分 |
| [BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) / [10M](https://huggingface.co/datasets/Mohammadta/BEAM-10M) | 常规三档 90 条、10M 10 条历史，共 2,000 probes | 只 chat 进入历史；全量结构扫描，案例仍为 100K 中两条；10M 为不同深层嵌套 | 主要增长的是历史长度；生成背景不能混入 Add，通用 evidence/评分待适配 |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | 5,000 题、200 人，400 份 32K/128K 历史；who/pref_type/updated/sensitive 等独立标注 | 两人完整 32K 历史研究包；排除 system 生成画像，保留对话；128K 未适配 | 他人信息、偏好更新、遗忘；522 他人信息题、1,048 遗忘题；标注不进 Add |
| [MemoryAgentBench](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench) | 四类完整 Parquet，146 context / 3,671 questions；answer、类别及部分 keypoints | 冲突类一题完整 455 事实 pack，人工核对三跳路径 | 检索/冲突/长理解/从示例学习要分开评分；电影答案可为实体 ID；未做全量通用适配 |
| [PersonaMem-v3](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3) | samples 三表：100 人、221,817 事件、15,791 query、31 任务类型 | 两题按同 persona 且严格早于 query 筛选；顶层/嵌套生成标签隔离，保留独立 user_message | 跨应用反馈、时间切面、记忆限制；不能把隐式负信号等同永久厌恶；不宣称超出取得范围 |
| [ScriptMem](https://github.com/memorax-ai/ScriptMem) | 457 题、选项与任务元数据；缺真实剧本 | 任务包可用，缺历史明确标记 | 仅分析题型；不能用问题或合成 schema 代替历史 |

统计单位不可混淆：BEAM 的一条历史包含许多发言，PerLTQA 的一个来源单元可能是一整份文档，MAB 的一个 context 可对应多题。所有研究包保留来源身份和选择条件；没有用答案修复原始事实。

## 从数据到设计的使用顺序

1. LongMemEval、LoCoMo：先建立日期、主体、证据位置和完整链的对照。
2. PersonaMem-v2：增加引用归属、更新、遗忘边界；不要把被请求编辑的他人简介记成用户本人。
3. M01：检验关系补齐；问句里没有后两跳实体名称，一次关键词召回容易只到第一跳。
4. BEAM、CL-bench/Life：扩大历史或任务约束，分别报告相关性、覆盖和工作结果。
5. PersonaMem-v3：加入提问时间截断、跨应用反馈和当前帮助/长期记忆的区分。

原文→可用记忆→检索候选→最终上下文→回答分别记录；设计路径与真实执行分开。人工选例用于解释和回归，全量效果必须另外验证。未来方法对比按 persona/context/对话整组留出，避免共享历史泄漏。
