# 数据集：来源、读取与准备

`dataset/` 是独立数据层，负责原始数据获取、结构分析、预处理、选择与切分。数据集无需与比赛或待测系统绑定，产物是中立的 dataset pack；Add/Search、分块、角色映射和评分属于 [`benchmark/`](../benchmark/README.md)。依赖方向为 `benchmark → dataset`。

## 已取得的数据（2026-10-07）

| 来源 | 本机实际取得 | 读取与使用 |
| --- | --- | --- |
| [LoCoMo 作者原版](https://github.com/snap-research/locomo) | 完整 JSON：10 对话、272 会话、5,882 turns、1,986 QA | 保留 speaker、turn ID、时间、caption、QA/evidence；按 conversation/session/category 选择。CC BY-NC 4.0。 |
| [LoCoMo-Refined 社区版](https://github.com/mem-eval-suite/LoCoMo_refined) | 完整 raw JSON、questions JSONL；10 对话、1,382 QA；固定 commit `8870911…` | 同一读取结构，独立来源身份；不使用生成 summary 充当原文。CC BY-NC 4.0，参见 NOTICE。 |
| [ScriptMem](https://github.com/memorax-ai/ScriptMem) | 4 个 raw QA 文件、questions JSONL、manifest；457 题 | 分析题型、选项和来源，生成任务 pack；作者未发布真实剧本/对话。CC BY-NC 4.0 仅覆盖作者的任务材料。 |
| [CL-bench](https://huggingface.co/datasets/tencent/CL-bench) | 完整 JSONL，1,899 题 | 原三条 smoke 中 1 条可按多轮边界拆分，2 条上下文与任务混在单条消息中，原样保留待适配；全量尚未转 pack。 |
| [CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life) | 完整 JSONL，405 题 | 单轮用 TASK 分隔符；多轮用最后用户消息为任务，rubrics 独立保存；现有案例 pack 继续使用。 |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | 文本 benchmark 5,000 题、200 persona，400 份配套 32K/128K 历史 | 可显式连接 32K 历史；已生成 persona 521 的 188 turns / 3 tasks smoke。128K 完整取得但当前未适配。CC BY 4.0。 |
| [BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) | 常规三档 90 条、10M 两片 10 条；逐批解码通过 | 仅 chat 作为历史；现有小样本 reader 可用，全量 Parquet 尚未转 pack。CC BY-SA 4.0。 |
| [PerLTQA 中文](https://github.com/Elvin-Yiming-Du/PerLTQA) | 完整中文 memory/QA：141 人物档案，32 人物有 8,593 题 | 新 reader 保存结构化来源文档、关系和原始时间；QA 引用可解析，字符 anchors 未认证。CC BY-NC 4.0。 |

CL-bench 两版均为作者的 [evaluation-only 许可](https://huggingface.co/datasets/tencent/CL-bench/blob/main/LICENSE.txt)，仅用于评测/测试，禁止训练、微调、校准、蒸馏等参数更新。

[LongMemEval S/M/Oracle](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) 已取得固定 revision `98d7416` 的完整文件，并实现共同读取器；S/Oracle 有 smoke pack，三档均已流式结构扫描。`_abs` 拒答题与可回答题分开统计。BEAM 常规三档、[BEAM-10M](https://huggingface.co/datasets/Mohammadta/BEAM-10M) 也已下载并逐批解码。MemoryAgentBench 四类已取得，仅一条冲突类研究样本转 pack，尚无全量通用适配。PersonaMem-v2 的 benchmark 与 400 份历史已取得，两人完整 32K 历史用于研究；PersonaMem-v3 只取得 samples 三表，已做两个时间切片。没有找到可独立获取并核验来源的 LongMemEval-Refined 发布，故没有虚构文件或读取器。

[`catalog.json`](./catalog.json) 统一登记来源；`pack_adapter` 表示代码能力，`local_verification` 表示真实数据验证状态，`local_acquisition` 记录本机取得范围。来源可用、读取器支持和本机取得范围是不同事实。[最新获取记录](../docs/doing/2026-10-07-huggingface-retry.md)与[样本案例库](../casestudies/README.md)列出核验结果和限制。

## 全量研究与案例包

`python -m dataset.survey --include-m` 扫描新下载的完整来源，输出 `data/research/survey.json` 并校验 receipt；含 Parquet 的研究使用 `benchmark/requirements-research.txt` 的隔离环境依赖。CL-bench 全量有 621 题可按现有规则拆分，1,278 题边界未认证；Life 405 题均可拆分。它们尚未进行完整方法评分。

`python -m dataset.research_cases` 重建五个研究包：LongMemEval 三题完整 S 历史、PersonaMem-v2 两人完整 32K 历史、MemoryAgentBench 一题完整 455 事实、PersonaMem-v3 两题严格时间切片，以及六条件短片段实验。MAB/v3 当前是限定研究切片，未实现通用全量评测适配。

LongMemEval 的 `YYYY/MM/DD (Weekday) HH:MM` 日期原先未被解析，本轮已修复，保留 source_date 和无时区的归一化假设。旧 pack 需要重建。PersonaMem-v3 按同 persona 且早于提问时刻筛选；去掉顶层和嵌套生成标签，保留独立 user_message 中的记忆限制。详细范围见[研究记录](../docs/doing/2026-10-07-dataset-research.md)。

## 新取得数据的小样本

```powershell
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset longmemeval-s --question-limit 6 --output dataset/data/prepared/longmemeval-s-smoke.json
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset longmemeval-oracle --question-limit 6 --output dataset/data/prepared/longmemeval-oracle-smoke.json
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset personamem-v2 --history-root dataset/data/raw/personamem-v2 --persona-ids 521 --task-limit 3 --output dataset/data/prepared/personamem-v2-persona521-smoke.json
```

PersonaMem-v2 不传 `--history-root` 时仍只生成带历史引用的任务包；显式传入才加载对应 32K 文件，校验 persona、文件哈希与 receipt。当前排除历史内的 system 人物生成画像，保留 user/assistant 原文；此输入选择记入 preparation，不等同原版完整评测协议。128K、完整人物覆盖和原版 Answer/Eval 需后续适配。

LongMemEval 依据作者评估代码的 `_abs` ID 规则区分拒答题；它们仍可能有 `answer_session_ids`，不能用“来源会话非空”判断可回答。重复上游 session ID 获得独立 pack ID，并保留 `source_id`。来源规则见[作者评估实现](https://github.com/xiaowu0162/LongMemEval/blob/main/src/evaluation/evaluate_qa.py)。

## 中文 PerLTQA

```powershell
.\.venv\Scripts\python.exe -m dataset.fetch perltqa-zh --github-api
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset perltqa-zh --output dataset/data/prepared/perltqa-zh-full.json
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset perltqa-zh --character-names 张小红,王小明 --output dataset/data/prepared/perltqa-zh-cases.json
```

memory/QA 双文件分别核对来源回执；可用 `--qa-input` 指定配对题目文件。默认覆盖全部有 QA 的 32 人：2,211 个来源文档单元、8,593 题。这里的 session 是资料分区，turn 是来源文档，不是按时间发生的真实交互。生成的结构化记忆和普通聊天输入应分别报告；原始材料存在矛盾，全部引用可解析不等于答案全部正确。不得将 gold 答案用于修复 Add 输入。

## 目录与获取

```text
dataset/
  catalog.json       来源、许可、原始文件、读取能力
  fetch.py           直接文件 / GitHub API / HF 行快照获取
  prepare.py         读取、统计、原始行切片、pack 构建
  pack.py            中立结构校验与读写
  split.py           按来源分组切分 dev/holdout
  data/              全部被 Git 忽略
    raw/             完整上游文件与 receipt
    snapshots/       HF 原始响应、无截断行提取与 receipt
    prepared/        中立 pack 与本地切片
```

每个新下载文件有 `.receipt.json`，记录来源 URL、SHA-256、大小、取得时间。GitHub API 获取额外校验 Git blob hash。HF 行 API 不固定仓库 revision：保留原始响应和内容哈希，明确标记为缓存快照；检测到截断/partial 时拒绝导出。

```powershell
.\.venv\Scripts\python.exe -m dataset.fetch locomo-refined-community --github-api
.\.venv\Scripts\python.exe -m dataset.fetch scriptmem --github-api
.\.venv\Scripts\python.exe -m dataset.fetch clbench-life --sample-rows 3
.\.venv\Scripts\python.exe -m dataset.fetch beam --sample-rows 1
```

相同行快照不会覆盖；新范围用 `--offset`。完整文件下载为 `python -m dataset.fetch <id>`。本轮网络恢复后已验证固定 revision 的 HF resolve 完整下载；大文件仍需保留 receipt 并按范围切片，避免把全量原文直接送入 Add/Search。命令从仓库根目录执行，只需标准库；Parquet 解码使用本地核验工具，不改变项目环境。

## 分析、预处理与切分

```powershell
.\.venv\Scripts\python.exe -m dataset.prepare inspect --dataset locomo
.\.venv\Scripts\python.exe -m dataset.prepare inspect --dataset scriptmem
.\.venv\Scripts\python.exe -m dataset.prepare inspect --dataset beam --input dataset/data/snapshots/beam/100K-0-1.jsonl
.\.venv\Scripts\python.exe -m dataset.prepare slice --dataset scriptmem --limit 10 --output dataset/data/prepared/scriptmem-rows.jsonl
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset locomo --conversation-ids conv-26 --session-limit 4 --category 1 --category 2 --category 4 --questions-per-category 2 --output dataset/data/prepared/locomo-smoke.json
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset clbench-life --input dataset/data/snapshots/clbench-life/train-0-3.jsonl --task-limit 3 --output dataset/data/prepared/clbench-life-smoke.json
.\.venv\Scripts\python.exe -m dataset.prepare build --dataset beam --input dataset/data/snapshots/beam/100K-0-1.jsonl --task-limit 10 --output dataset/data/prepared/beam-smoke.json
```

原始行切片支持 JSON 数组、JSONL、CSV，记录输入哈希和 offset，不覆盖原始文件。LoCoMo 类别为 `1=multi_hop / 2=temporal / 3=open_domain / 4=single_hop / 5=adversarial`，同时保留原数值。LoCoMo、LongMemEval 限制会话后移除证据不完整的问题。LoCoMo 的排除题号与缺失 turn ID 写入 `preparation.excluded_tasks`；即使保留全历史，原版仍有 2 题引用不存在的 turn，故完整 pack 为 1,984 题。LongMemEval 可按 `--question-ids / --question-type / --question-limit` 选择。BEAM/ScriptMem/PersonaMem 支持在选中来源文件内用 `--task-ids` 选择具体任务。

有多个独立来源组的 pack 可以切分：

```powershell
.\.venv\Scripts\python.exe -m dataset.split --input dataset/data/prepared/locomo-full.json --output-dir dataset/data/prepared/locomo-split --seed 42 --holdout-fraction 0.2
```

按 `group_id`（否则 `record.id`）整组切分：PersonaMem 同 persona、ScriptMem 同作品对话、CL-bench 同 context_id 不跨集合；LoCoMo 以对话为组。仅有一个组时拒绝切分。新来源需先审查共享历史的分组关系；此命令不会复原上游官方 split。

## pack 语义

顶层为 `dataset / preparation / records`；每条记录含 `id / sessions / tasks`：

- `sessions[].turns[]` 保存源 turn ID、content、speaker 或原始 role、时间等。双人对话仅存 speaker/participants，协议角色由下游决定。
- `tasks[].input` 保存 text/options/messages；没有可靠上下文边界时保留原消息结构。
- `tasks[].annotations` 独立保存 answer、evidence、rubric、偏好等标注；它们不属于历史。
- `history_status / history_references` 表示缺失历史及来源引用，不能用答案或合成对话代替。
- `preparation` 保存输入 SHA、获取 receipt、选择条件和工具版本。相同来源与选择可重建相同内容。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s dataset/tests -v
```

覆盖流式读取、证据筛选、上下文边界、标注隔离、BEAM probes、分组切分与原始文件保护。实际数据及派生内容只保留在被忽略的 `data/`。
