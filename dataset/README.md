# 数据集：来源、读取与准备

`dataset/` 是独立数据层，负责原始数据获取、结构分析、预处理、选择与切分。数据集无需与比赛或待测系统绑定，产物是中立的 dataset pack；Add/Search、分块、角色映射和评分属于 [`benchmark/`](../benchmark/README.md)。依赖方向为 `benchmark → dataset`。

## 已取得的数据（2026-10-05）

| 来源 | 本机实际取得 | 读取与使用 |
| --- | --- | --- |
| [LoCoMo 作者原版](https://github.com/snap-research/locomo) | 完整 JSON：10 对话、272 会话、5,882 turns、1,986 QA | 保留 speaker、turn ID、时间、caption、QA/evidence；按 conversation/session/category 选择。CC BY-NC 4.0。 |
| [LoCoMo-Refined 社区版](https://github.com/mem-eval-suite/LoCoMo_refined) | 完整 raw JSON、questions JSONL；10 对话、1,382 QA；固定 commit `8870911…` | 同一读取结构，独立来源身份；不使用生成 summary 充当原文。CC BY-NC 4.0，参见 NOTICE。 |
| [ScriptMem](https://github.com/memorax-ai/ScriptMem) | 4 个 raw QA 文件、questions JSONL、manifest；457 题 | 分析题型、选项和来源，生成任务 pack；作者未发布真实剧本/对话。CC BY-NC 4.0 仅覆盖作者的任务材料。 |
| [CL-bench](https://huggingface.co/datasets/tencent/CL-bench) | 官方行 API 前 3 条完整记录；全量 1,899 题 | 已取得样本中 1 条可按多轮边界拆分，2 条上下文与任务混在单条消息中，原样保留待适配。 |
| [CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life) | 官方行 API 前 3 条完整记录；全量 405 题 | 单轮用 TASK 分隔符；多轮用最后用户消息为任务，保留此前历史；rubrics 独立保存。 |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | `benchmark_text` 前 3 条，均属 persona 521；该 split 为 5,000 题 | 读取 CSV/JSONL，保留历史引用；对应 32K 历史下载仍为 502，pack 标记缺失。CC BY 4.0。 |
| [BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) | `100K` split 第 1 个完整对话：3 个批次、188 turns；该 split 为 20 对话 | 仅 chat 作为历史；提取 10 类 probes，ideal_response/rubric 独立保存。CC BY-SA 4.0。 |

CL-bench 两版均为作者的 [evaluation-only 许可](https://huggingface.co/datasets/tencent/CL-bench/blob/main/LICENSE.txt)，仅用于评测/测试，禁止训练、微调、校准、蒸馏等参数更新。

[LongMemEval S/M/Oracle](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) 已登记作者源（MIT）并实现共同读取器；S 完整文件此前下载失败，本轮 Oracle 完整文件返回 502，S/Oracle 行 API 返回 500，尚无本机真实数据。M、[BEAM-10M](https://huggingface.co/datasets/Mohammadta/BEAM-10M) 本轮未下载。没有找到可独立获取并核验来源的 LongMemEval-Refined 发布，故没有虚构文件或读取器。

[`catalog.json`](./catalog.json) 统一登记来源；`pack_adapter` 表示代码能力，`local_verification` 表示真实数据验证状态。来源可用、读取器支持和本机取得范围是不同事实。[本轮记录](../docs/doing/2026-10-05-dataset-decoupling.md)列出下载情况与限制。

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

相同行快照不会覆盖；新范围用 `--offset`。完整文件下载为 `python -m dataset.fetch <id>`。当前普通 raw/HF resolve 入口不稳定，GitHub API 和部分 HF rows endpoint 已验证可用。命令从仓库根目录执行，只需标准库。

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
