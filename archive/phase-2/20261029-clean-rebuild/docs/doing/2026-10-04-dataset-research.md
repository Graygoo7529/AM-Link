# AML 基准名称与公开上游数据源调研

> 本文保留 2026-10-04 初版调研记录。当前获取范围、来源 schema 与设计以 [2026-10-05 更新](./2026-10-05-dataset-decoupling.md)及 [dataset](../../dataset/README.md)为准；数据不再要求与比赛关联。

调研日期：2026-10-04；状态：`done`。优先查看各数据集作者/维护方仓库和数据卡；AML 资料只用于确认比赛公开名称、Add/Search contract 与隐藏数据边界，不把官方基准卡当数据源。

## 结论

可以立即使用的原始数据包括本地已有的 SNAP LoCoMo 原始版；可从作者源取得的候选还包括 LongMemEval S/M/Oracle、LoCoMo-Refined 社区发布版、CL-bench / CL-bench Life、PersonaMem-v2 和 BEAM。ScriptMem 公开 457 道题及任务材料，但没有原始剧本/对话，所以不能组成完整的记忆 Add/Search 输入。

“数据源可公开取得”不等于“有许可把它交给外部服务”“存在 gold evidence”“能复算完整基准分”或“它就是 AML 的冻结版本”。机器可读来源、许可与使用备注见 [`dataset/catalog.json`](../../dataset/catalog.json)；只有 LoCoMo 和 LongMemEval-S 已接入当前转换器。

## 来源核验

| 数据集 | 作者/维护方数据源与公开内容 | 本地准备和评测方式 | 状态与边界 |
| --- | --- | --- | --- |
| LoCoMo 原始版 | [SNAP 作者仓库](https://github.com/snap-research/locomo) 发布 `locomo10.json`：10 对话、session 历史、约 5.9K turns、1,986 QA，CC BY-NC 4.0 | 按对话建 user scope，按 session/turn 有序 Add；QA `evidence` 中 `dia_id` 映射源 turn，Search question，算 turn evidence recall、rank 和 multi-hop chain coverage | `dataset/data/raw/locomo/locomo10.json` 已取得并校验 SHA。它只是 LoCoMo 原版，不是 AML Refined。 |
| LoCoMo-Refined 社区候选 | [mem-eval-suite/LoCoMo_refined](https://github.com/mem-eval-suite/LoCoMo_refined) 发布 `data/raw/locomo_refined.json`、`data/public/questions.jsonl`、`conversations.jsonl` 和 manifest；README 报告 10 conversations、1,382 questions；CC BY-NC 4.0，NOTICE 说明由 SNAP 原版修改 | 对齐 public QA 与对话/session 原文，按作者 answer evaluator 做端到端复算；若做 Add/Search evidence 召回，先检查它是否保留原始 evidence span。revision 已固定为 `887091190789e8d6760e70b9edd696539923dc4f` | 公开第三方候选；pinned raw JSON 下载返回 HTTP 502，文件 SHA 和 schema 尚未本地复核。它使用同名“LoCoMo-Refined”，但无证据证明等于 AML 冻结包。 |
| ScriptMem v1.0 | [MemoraX/Oxford 作者仓库](https://github.com/memorax-ai/ScriptMem)：457 questions，来自 Friends、12 Angry Men、The Man from Earth、An Enemy of the People；原剧本/原对话因版权不含在仓库。CC BY-NC 4.0 仅适用于 ScriptMem 原创题目、标注、协议和文档 | 可检查六类题型、选项、参考答案和作者 answer evaluator；不能把 synthetic schema 例子当真实 history，也不能把 question/answer 当 Add 输入 | 可取得 QA 材料，不能完整模拟输入历史；不做 Add/Search 指标。 |
| LongMemEval-S | [作者仓库](https://github.com/xiaowu0162/LongMemEval) 与[作者 HF 清理集](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) 提供 `longmemeval_s_cleaned.json`；MIT 清理数据卡；500 questions，约 115K tokens / 40 sessions per history | 按 question_id 逐条读取有序 `haystack_sessions`；对话按最多 20 messages Add；`has_answer` turn 映射为检索目标。作者另提供 GPT-4o QA judge，答案评估需单独使用 | 已有转换器；文件约 277 MiB，本轮 pinned 下载返回 HTTP 502，未留下 `.partial`。 |
| LongMemEval-M | 同一作者清理集提供 `longmemeval_m_cleaned.json`，500 questions、每问约 500 sessions | 输入不能随意截断后与全量分数比较；先以单问题固定完整 history 做预算测试。沿用 `has_answer` 检索评估和作者答案评测 | 源已确认、未下载；不作为默认 smoke。 |
| LongMemEval Oracle | 同一作者源 `longmemeval_oracle.json`，每问仅保留 evidence sessions | 可校验 evidence adapter 和 evaluator 数据链；历史难度低于 S/M | 源已确认、未下载。仅做 sanity check，单独报告，不与 S/M 混分。 |
| CL-bench | [Tencent Hunyuan/Fudan 作者仓库](https://github.com/Tencent-Hunyuan/CL-bench) 和[作者 HF 卡](https://huggingface.co/datasets/tencent/CL-bench)：1,899 rows，`messages`、`rubrics`、`metadata`，约 90 MB | 按消息结构拆 context 与 task；context/history 给 Add，task 给 Search/reader。Rubrics 只进入 evaluator；用作者或兼容的任务 judge 计分 | 自定义 evaluation-only license：只允许模型评测/测试/benchmark，禁止训练、fine-tuning、校准、蒸馏、适配或任何参数更新。未下载。 |
| CL-bench Life | [作者 HF 卡](https://huggingface.co/datasets/tencent/CL-bench-Life)：405 rows、29.3 MB，日常历史场景，字段为 `messages/rubrics/metadata` | 与 CL-bench 相同；从任务 context 拆出时间有序输入，rubrics 仅留给 judge。没有公开源-span 时不报 evidence recall | 同一评测专用许可；未下载。 |
| PersonaMem-v2 | [Penn 官方仓库](https://github.com/bowen-upenn/PersonaMem-v2) 和[HF 数据卡](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2)：1,000 personas、20,000+ preferences；benchmark query split 5K rows，字段引用 32K/128K histories；HF 卡标 CC BY 4.0 | 固定 split/persona，单独取得链接 history 并逐文件核验许可；history 加入 memory，`user_query` 发 Search。`preference`、correct/incorrect answers 和相关 snippet 不写入 Add；要重现答案级指标需作者评测流程 | 数据卡公开但历史部分有外链；读取器未实现，也未下载。 |
| BEAM 128K/500K/1M | [作者仓库](https://github.com/mohammadtavakoli78/BEAM) / [作者 HF 卡](https://huggingface.co/datasets/Mohammadta/BEAM)：90 rows；多个领域和十类记忆能力。Data CC BY-SA 4.0，代码 MIT | 从一条 128K conversation 起步，流式读取 `chat`，按 API 上限切 Add；`user_questions/probing_questions` 和 gold answers 保留给 evaluator。报告每条样本的真实输入规模、检索结果和成本 | 公共源可取；需单独 reader，尚未下载。 |
| BEAM-10M | [作者 BEAM-10M HF 卡](https://huggingface.co/datasets/Mohammadta/BEAM-10M)，10M token 档，Data CC BY-SA 4.0 | 单独高成本压力层；先估算流式读、存储、目标系统 provider 调用和费用，再选择个别对话 | 不默认取数或回放；尚未下载。 |

## 名称与 AML 的关系

AML Cycle 2 官方[基准卡/文档](https://agentmemories.ai/zh-cn/docs)及[公开评测仓库](https://github.com/AML-memory/agent-memory-leaderboard)用于确认比赛需要参赛者提供 Add/Search。公开实现仓库提供配置和 protocol，不包含 held-out corpus、私有 annotations 和正式 participant run artifacts。因此：

- LoCoMo 作者原版、LoCoMo 同名 community refined、AML 的 `LoCoMo-Refined` 要作为三个不同来源版本跟踪；community release 不能未经核对就称作 AML 原包。
- AML 文本列表出现 `LongMemEval-Refined` 和 `LongMemEval-S`，公开 contract ID 都映射为 `longmemeval`。本次未找到作者/维护方发布、能够确认等于 AML `LongMemEval-Refined` 的独立公开包；作者 S/M/Oracle 只作为公开上游评测。
- `ScriptMem` 的公开问题/答案不提供版权文本，不能重建真实 conversation Add 历史。
- `CL-bench` / `CL-bench Life` 是任务上下文和 rubric 评估基准，不是天然的检索证据标注集。若用于本地靶场，必须将 `rubrics`、答案等留在 evaluator 侧。
- 正式与本地均由官方 Answer/Eval 负责的原参赛 contract，与靶场公开源证据召回分开报告。公开源结果用于找退化样本和排查 Add/Search 行为，不冒充官方 leaderboard 分数。

## 推荐接入顺序

1. 保留本机 LoCoMo smoke，完善逐条证据到 Add request 的追踪；它反馈快、原文和 evidence mapping 完整。
2. 网络允许时先取得 LongMemEval-S 固定 HF revision，计算本地 SHA，再运行单问/少 session 检查；之后扩到完整 S。M/Oracle 单独开切片和报告。
3. 核对 community LoCoMo-Refined commit、NOTICE 和字段后决定是否增加 builder；正式 AML bundle 身份仍保持未验证。
4. PersonaMem-v2、CL-bench-Life、CL-bench 要实现将 context 和 task/rubric 分离的读取器/evaluator。先用人工选定的小 split，且严格隔离评测标签。
5. BEAM 先一条 128K 对话后逐档扩；10M 必须有独立资源/费用上限。
6. ScriptMem 只有在数据作者/版权方另行公开可用原剧本文本并确认其权利后，才考虑本地 Add/Search replay。

## 来源记录

- SNAP LoCoMo 作者源：[仓库](https://github.com/snap-research/locomo)。
- LoCoMo-Refined 第三方候选：[仓库](https://github.com/mem-eval-suite/LoCoMo_refined)、[NOTICE](https://github.com/mem-eval-suite/LoCoMo_refined/blob/main/NOTICE)。
- ScriptMem：[作者仓库](https://github.com/memorax-ai/ScriptMem)。
- LongMemEval：[作者 README](https://github.com/xiaowu0162/LongMemEval)、[作者 HF 清理数据卡](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)。README 列出 S/M/Oracle 三个 JSON、turn `has_answer` 和 answer-session 标注，以及作者检索和 QA 评测脚本。
- CL-bench：[作者仓库](https://github.com/Tencent-Hunyuan/CL-bench)、[基础集 HF 卡](https://huggingface.co/datasets/tencent/CL-bench)、[Life HF 卡](https://huggingface.co/datasets/tencent/CL-bench-Life)。两个数据卡列明 custom evaluation-only license。
- PersonaMem-v2：[Penn 作者仓库](https://github.com/bowen-upenn/PersonaMem-v2)、[HF 数据卡/许可](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2)。
- BEAM：[作者仓库](https://github.com/mohammadtavakoli78/BEAM)、[128K/500K/1M HF 卡](https://huggingface.co/datasets/Mohammadta/BEAM)、[10M HF 卡](https://huggingface.co/datasets/Mohammadta/BEAM-10M)。
