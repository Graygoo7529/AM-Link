# 案例实验与研究工作区

2026-10-30。唯一案例catalog在 `research/cases/catalog.json`，唯一展示页面在 `research/data/index.html`。正式方法只提供Add/Search；这里另行运行Answer/Eval诊断。

## 选择一题、一个切片或完整历史

以下命令在项目根目录执行；lexical不调用模型：

```powershell
.\.venv\Scripts\python.exe -m research.benchmark study --case lm4 --scope full --target lexical
.\.venv\Scripts\python.exe -m research.benchmark study --case lm4 --scope anchors --target lexical
.\.venv\Scripts\python.exe -m research.benchmark study --case lm4 --scope window --radius 2 --target lexical
.\.venv\Scripts\python.exe -m research.benchmark study --dataset-pack dataset/data/prepared/locomo-full.json --record conv-26 --task qa-11 --plan-only
```

full是该记录的完整准备历史，不是数据集全量。anchors/window使用研究者指定来源，属于辅助诊断，不当成完整历史成绩；没有锚点的案例应跑full。移除标注证据默认拒绝，显式allow-partial才保留并标不可评分。before为严格早于毫秒时间；没有时间的材料不猜。

真实第三版调用使用native工厂；显式载入私有配置后调用同一入口，例如在Python中：

```python
from amlink.config import load_env_file
from research.benchmark.study import main
load_env_file("docs/private/amlink.env")
main(["--case", "lm4", "--scope", "full", "--target", "native",
      "--factory", "amlink.native:create_method", "--run-id", "my-new-run"])
```

使用新运行ID；不会覆盖已有结果。默认生成完整请求计划、数据快照、API轨迹和内部步骤，登记后重建页面。可用no-view延后统一构建；no-register用于批量结束后串行登记。

## 六类100题完整历史

```powershell
.\.venv\Scripts\python.exe -m research.benchmark.broad prepare --output research/benchmark/data/plans/<new-plan>
.\.venv\Scripts\python.exe -m research.benchmark.campaign --plan research/benchmark/data/plans/<new-plan>/suite.json --prefix <new-run> --env-file docs/private/amlink.env --workers 3
```

默认固定种子20261029，六类26历史100题；目前包对应780 Add。prepare冻结源码/数据哈希，不调模型；campaign新库完整Add后Search，再Answer/Eval，每阶段单次、不重试。当前每历史记忆调用预算1000次/500万输入字符；不把历史r6预算当今天默认。失败保留在总分母。源码或路径迁移后必须重新prepare，不把新结果拼到旧冻结清单。

## 独立Answer、评分与评注

```powershell
.\.venv\Scripts\python.exe -m research.benchmark answer --run research/benchmark/data/runs/<run-id> --env-file docs/private/amlink.env --answer-id <new-answer> --max-questions 100
.\.venv\Scripts\python.exe -m research.benchmark workspace publish
```

Answer默认GPT-5.4、medium、120秒、8192 completion tokens（含推理）；只接收问题和Search真实输出，标注仅评分侧可见。可显式指定其它研究模型，默认推理参数只随默认型号附加，无自动切换。campaign使用同一Answer默认，将mini辅助评分保留在evaluation.jsonl；协议失败不重发，Codex复核另存且不覆盖原评分。费用无可核验单价时保持未知。

页面可下载评注文件，然后导入：

```powershell
.\.venv\Scripts\python.exe -m research.benchmark workspace import-note --run research/benchmark/data/runs/<run-id> --file <note.json>
```

评注绑定运行、数据、轨迹、问题与可选步骤，校验后追加；用supersedes修订旧解释。新运行自动进入单页索引；批次聚合在research/workspace.json登记。用户无需保存页面选择状态。

## 可观测性接入

native工厂签名factory(recorder, artifacts)，返回实现标准Add/Search的target，按[观测协议](OBSERVABILITY.md)记录真实输入/输出。第三版参考 `amlink/native.py` 与 `amlink/observation.py`。完整原文和artifact只在忽略目录；不记录密钥、Authorization或不受控异常正文。没有采集的步骤不能由展示器编造。
