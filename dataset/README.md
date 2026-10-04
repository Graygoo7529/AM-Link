# 数据集目录

本目录登记可取得的上游原始数据及处理/评测边界。`catalog.json` 中 `datasets` 是当前已接入读取器的源；`public_sources` 是来源已核验、可公开获取或可查看、但还未接入转换器的候选项。原始文件、切片 manifest 和 run trace 放在 Git 忽略的 `dataset/data/`，不会随代码提交。

## 可选数据

| 数据集 | 来源与许可 | 当前用途与限制 |
| --- | --- | --- |
| LoCoMo 原始版 | [SNAP 作者仓库](https://github.com/snap-research/locomo)，CC BY-NC 4.0；本机已取得 10 个对话、272 sessions、5,882 turns、1,986 QA | 已有读取、按 conversation/session/category 选题、按消息数分 Add、turn evidence 召回。它不是 AML LoCoMo-Refined。 |
| LoCoMo-Refined 社区发布候选 | [mem-eval-suite/LoCoMo_refined](https://github.com/mem-eval-suite/LoCoMo_refined)，commit `887091190789e8d6760e70b9edd696539923dc4f`，CC BY-NC 4.0；1,382 questions，提供 raw JSON 和 public JSONL | 已固定 revision；下载本轮返回 HTTP 502，文件和 SHA 尚未取得。该社区项目是否对应 AML 冻结 bundle 未验证，不能以此声称复刻官方版本。 |
| LongMemEval-S | [作者仓库](https://github.com/xiaowu0162/LongMemEval) / [作者 HF 数据集](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)，MIT；500 questions，约 115K tokens/question | 已实现读取器；约 277 MB 尚未下载。可按 question ID/type、session 数切片，保留 `has_answer` turns 作为 evidence；完整 Answer/QA judge 是单独阶段。 |
| LongMemEval-M | 同一作者源和 MIT 清理集；500 questions、每问约 500 sessions | 源已登记、读取器可复用；文件尚未下载。只选一题做切片仍可能很大，先核算输入/存储预算。 |
| LongMemEval Oracle | 同一作者源和 MIT 清理集；只保留 gold evidence sessions | 适合验证证据链路，不代表 S/M 的检索难度，不与其得分直接比较。 |
| ScriptMem v1.0 | [作者仓库](https://github.com/memorax-ai/ScriptMem)，457 questions、4 部作品、6 类问题；CC BY-NC 仅覆盖作者原创 benchmark materials | 原剧本/对话不发布，公开 QA 不足以构建 Add history。不可把答案写入 memory；暂不适合作为完整本地 Add/Search replay。 |
| CL-bench | [Tencent/Fudan 作者仓库](https://github.com/Tencent-Hunyuan/CL-bench) / [HF 数据集](https://huggingface.co/datasets/tencent/CL-bench)，1,899 tasks，90.1 MB | `messages/rubrics/metadata`。自定义 evaluation-only 许可只准评测，不准训练、微调、校准、蒸馏、适配或更新参数。需拆分 context/task 并接 rubric evaluator；尚未下载。 |
| CL-bench Life | [HF 作者数据集](https://huggingface.co/datasets/tencent/CL-bench-Life)，405 tasks，29.3 MB | 日常上下文版本；同为 evaluation-only。拆分 context/task，rubrics 只交 evaluator，不进入 Add；尚未下载。 |
| PersonaMem-v2 | [Penn 作者仓库](https://github.com/bowen-upenn/PersonaMem-v2) / [HF 作者数据集](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2)，HF 卡标 CC BY 4.0 | 1,000 personas、20,000+ preferences；5,000-row query split 引用 32K/128K history。需固定 split/persona 和逐个核验外链历史许可；answer/preference labels 不能进入 Add。 |
| BEAM 128K/500K/1M | [作者仓库](https://github.com/mohammadtavakoli78/BEAM) / [HF 数据集](https://huggingface.co/datasets/Mohammadta/BEAM)，benchmark data CC BY-SA 4.0，代码另为 MIT | 作者释放 90 个对话。先从一个 128K conversation 开始；questions/answers 留在 evaluator 侧。支持多尺度压力评估但不是本地 smoke 默认项。 |
| BEAM-10M | [作者 HF 数据集](https://huggingface.co/datasets/Mohammadta/BEAM-10M)，benchmark data CC BY-SA 4.0 | 单独的大型压力层，不默认下载；须先做流式读取、磁盘和请求/模型预算评估。 |

逐项来源、版本、许可和评估流程记录在[数据源调研](../docs/doing/2026-10-04-dataset-research.md)和机器可读的[数据集清单](./catalog.json)。AML 官方公开配置用于确认比赛 contract；公开上游原始数据并不等同于官方私有/冻结 bundle。当前未发现公开的 AML `LongMemEval-Refined` 原始包；作者 LongMemEval S/M/Oracle 是独立公开版本。

## 原始数据与读取

当前本机可回放的是 `dataset/data/raw/locomo/locomo10.json`，SHA-256 为 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`。只获取被选中的数据，不做批量下载：

```powershell
.\.venv\Scripts\python.exe dataset\fetch.py locomo
.\.venv\Scripts\python.exe dataset\fetch.py longmemeval-s
```

查看和生成固定小切片：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py inspect --dataset locomo
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset locomo --conversation-ids conv-26 --session-limit 4 --category 1 --category 2 --category 3 --questions-per-category 2 --output dataset\data\derived\locomo-smoke.json
```

LongMemEval-S 文件可按固定 question ID/type 和 session 上限切片：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py inspect --dataset longmemeval-s
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset longmemeval-s --question-limit 1 --session-limit 8 --output dataset\data\derived\longmemeval-smoke.json
```

`prepare.py` 只映射数据和切片，不回答、不调用模型。LoCoMo 每不超过 20 个原始 turn 生成一个 Add，QA evidence `dia_id` 保留到 turn/session 和 Add request 的来源映射；LongMemEval 用 `has_answer` turn 标注建 target，不把 `answer` 写入 Add。截短后没有完整 gold evidence 的问题会被排除并记入 selection 规则。每份 manifest 记录输入 SHA、源 URI、许可和 builder version。

尚未接入转换器的公开数据，实施顺序建议为：LoCoMo-Refined 社区版（核对 revision 与 evidence mapping）→ LongMemEval-S（当前已有 reader）→ PersonaMem-v2/CL-bench-Life（实现 split reader 和隔离 answer/rubric 的 evaluator）→ BEAM（streaming 多尺度）→ CL-bench → ScriptMem（等待有权使用的原始 source text）。Oracle 仅作管线 sanity check；10M 放在独立压力计划中。

## 评分和数据边界

- 靶场目前复算的是公开任务的 Add/Search 协议表现、来源证据召回/排名和多证据覆盖，不等于 benchmark 的 answer accuracy，也不等于 AML 官方成绩。
- LongMemEval 上游 answer judge 可作为后续独立阶段；需明确配置 evaluator/模型、记录调用和费用，再生成端到端结果。当前靶场不调用模型。
- CLBench/CLBench-Life 的 rubric、PersonaMem 的 preference/answers、BEAM/ScriptMem 的问题答案只用于 evaluator，不能混入 memory Add。
- LoCoMo 和 ScriptMem 的 CC BY-NC 不用于商业用途。CLBench evaluation-only 条款严禁任何形式训练/参数更新。PersonaMem history 外链和所有数据均按其自身来源/许可检查；代码仓库 LICENSE 不自动适用于数据。
- trace 含原文、检索请求和返回证据，可还原样本内容。只用于本地，留在 Git 忽略目录，不上传或提交。不要将公开数据发往外部 API，除非操作者明确选用并配置相应服务。
