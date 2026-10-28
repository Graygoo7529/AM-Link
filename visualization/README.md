# AM-Link 研究可视化

2026-10-28最新：[工具协议与局部整理修订](../docs/doing/2026-10-28-tool-repair-implementation.md)、[18份档案台账](../docs/doing/2026-10-28-tool-repair-run-ledger.md)。新增失败层、实际输出额度、逐项审查前后、撤销依据与持久支持、未提交待办的展示。6个案例已有本地持久评注；当前本地页突出`tool28-lm4-r3`与`tool28-pv4-r3`：前者来源3/4，后者长历史因研究预算只接收32/41 Add、Search未执行，不能记为方法通过。页面11数据集/26案例，每题最多80个span，省略数量明确显示，完整轨迹仍在运行目录；可改选其他档案重新生成。

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --workspace --workspace-run tool28-lm4-r3 --workspace-run tool28-pv4-r3 --max-spans 80 --web
```

下方为此前阶段的展示快照，不代表当前活动登记只有两条。

2026-10-28 后续：[节点保真与审查实测](../docs/doing/2026-10-28-memory-integrity-implementation.md)增加 12 个新库诊断档案，最终为 `integrity28-lm4-r6`、`integrity28-p2-r6`、`integrity28-l1-r6`，每个案例已有持久评注。仍是三个案例切片，不是完整历史；来源齐不代表整理完整或图正确。下方仅两个运行是迁移完成时的历史状态。

统一展示入口：[独立网页](./index.html)。`view.html` 是同源会话片段；原始样本与轨迹的本地扩展版在被忽略的 `data/local/`。原案例文档仍保留在 [`casestudies/`](../casestudies/README.md)。

2026-10-28：[v4 迁移](../docs/doing/2026-10-28-embedding-v4-migration.md)已清理旧库及活动登记，历史轨迹/报告保留供离线研究。当前活动运行仅 `v4-1024-20261028-lm4`、`v4-1024-20261028-p2`，均使用新库、text-embedding-v4 / 1024 维；页面仍为 11 数据集、26 案例。下方 contract27 记录是清理前历史状态。

2026-10-27 当前已增加 `contract27-*` 新库真实实验及评注；历史清理记录见[10月26日备份清理](../docs/doing/2026-10-26-convergence-audit-and-reset.md)，未恢复旧库。最新[实施报告](../docs/doing/2026-10-27-delivery-contract-implementation.md)分别核对接收、整理及检索质量。Add 摘要现在显示接收结果、缓冲/未完成、组进度与内部错误；Search 显示局部停止及原因。HTTP 成功不代表内部无错误；旧轨迹未采集字段显示未知。公共版仍无原文运行，本地版选择档案加载。

## 四个连通视角

1. **数据构成**：本机取得范围、统计单位、全量结构分布、来源层级、处理前后区别。
2. **样本与标注**：原始字段走向历史、任务或评估侧；查看选定案例的真实来源摘录、问题、答案和 evidence 等标注。原文只在本地扩展版嵌入。
3. **理论链路与设计检查**：沿 Add → Search → Answer 查看合理处理、必要事实与来源；每阶段同时显示检查点和实现后应观测的信息。可直接跳转原样本或已有实测。
4. **运行观测与评注**：按查询查看真实写入、候选排序、Search 和已有 Answer/Eval；评注区分观察事实、假设与下一步实验。未采集的内部步骤保持未知。

2026-10-08 已扩至 26 个案例，新增多人物交集、事件顺序、条件分支、敏感信息最小化、撤回后不回流和推荐隐式反馈。已有完整 LongMemEval-S 的 BM25 对照、Mem0 六条件实验，以及跨数据集 Mem0 切片和 BEAM 冲突重跑；结果按证据覆盖、回答审查和依赖失败分开记录。实施见[研究闭环记录](../docs/doing/2026-10-07-research-infrastructure.md)，综述见[记忆研究调研综述](../docs/doing/2026-10-08-memory-research-survey.md)，设计建议见[记忆设计工作台](../docs/phase-2/memory-design-workbench.md)。

这是一套展示和分析层，不执行记忆系统或收费模型。无需保存页面选择。内容、数据来源与运行记录独立维护，网页和会话展示共同生成。

本地研究页顶部支持按案例编号（如 `LM04`、`B02`、`PV04`）检索。结果可直达理论链路，也可直接打开与案例绑定的运行观测。已登记但未载入的旧运行会显示为归档记录，并给出精确加载命令；原始轨迹仍只在本地运行目录中，不会整批嵌入网页。没有对应实测时只提供理论入口，不以空数据伪造观测。靶场可将冻结的一期 AM-Link 纳入统一对照：`--target phase1`，详见[案例实验工作区](../benchmark/STUDIES.md)。

## 构建与再次加载

推荐使用持久工作区恢复本机样本、已登记运行和评注（不会重跑模型）：

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --workspace --web
```

大型运行可以使用 `--max-queries N --max-spans N` 降低单页投影大小；页面会标出省略的步骤，完整 trace、report 和观测 artifact 不受影响。例如：`--workspace-run amlink-refactor-locomo-100-real-20261011b --max-queries 3 --max-spans 60`。

[案例实验指南](../benchmark/STUDIES.md)提供按案例、完整历史或片段运行的方法。默认显示最近最多五次登记运行；超出容量时明确减少较早运行，原档案保留。用重复的 `--workspace-run <运行 ID>` 指定要对照的运行。网页中的评注草稿需要导入工作区才能长期保存；命令行记录会自动更新页面。

[Mem0 六条件实测](../casestudies/mem0-microstudy.md)已接入：公共视图显示定性摘要，本地视图可查看写入后记忆、Search、Answer、逐例审查及 63 个 span。重新加载已有运行（不会调用模型）：

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --web --run benchmark/data/runs/mem0-microstudy-20261007 --run-kind experiment --observations benchmark/data/runs/mem0-microstudy-20261007/observations-reviewed.json
```

在仓库根目录：

```powershell
.\.venv\Scripts\python.exe -m visualization.build --web
.\.venv\Scripts\python.exe -m visualization.build --local --web
.\.venv\Scripts\python.exe -m visualization.build --local --run benchmark/data/runs/decoupling-verification-20261005 --run-kind fixture --web
```

第一条只输出可版本管理的研究结构和人工案例说明；后两条含本机数据摘录/运行结果，仅输出到 `visualization/data/local/`。现有 fixture 是测试服务的真实 HTTP 调用记录，不是 AM-Link/Mem0 质量实验。每次构建重新读取本机文件，不会自动监控或下载。

可多次传 `--run`，每个运行对应一个 `--run-kind fixture|experiment`；`fixture` 与真实目标实验必须分开解释。目标名称和版本直接来自原报告。`--observations <文件>` 可导入后续 Answer/Eval 及公开步骤记录，格式见 [设计与数据约定](./DESIGN.md)。

运行目录若有 `observability.jsonl`，会按 [标准接口 v1](../benchmark/OBSERVABILITY.md) 校验并展示内部步骤、来源关联与候选。完整用量声明放在 `observability.meta.json`；没有声明时不把缺少的调用记录当成零。

`--inline-output <当前会话可写目录/am-link-research.html>` 将同一片段复制到当前会话目录；最终回复通过 `visualize` 内容引用呈现。不要把完整网页 `index.html` 当作片段。下次用户说“加载研究可视化”，先读本文件和案例库，再构建所需视图；无需重做已核验分析。

`--check` 检查公共版本是否与源内容一致。网页导出复用已安装 visualize 技能，可用 `--renderer` 指定其 `scripts/render.py`。导出的网页包含资源，普通浏览器打开时不依赖 Python 或技能；当前内置浏览器只能通过 HTTP 预览，不尝试绕过其本地文件限制。

## 维护入口

- `profiles.json`：各数据源层级、字段语义与默认统计 pack；案例对应关系只从 catalog 读取。
- `research.json`：可发布的聚合统计与本地 BM25 结果摘要，保留源哈希，不含原文；由 `python -m visualization.research` 从忽略目录中的 census 与实验产物生成。
- `../casestudies/catalog.json` 和案例 Markdown：案例、数据绑定、必要事实/来源与设计检查的唯一来源，原案例网页继续可用。
- `sources.py`：从 pack 生成有限的真实样本摘录及统计，保留文件 SHA 与来源身份。
- `traces.py`：从 benchmark 产物提取可观测证据，验证 pack 身份和任务对应，不复制鉴权配置或任意 raw response。
- `spans.py`：校验内部步骤的父子关系、来源引用及请求身份；缺失父步骤标记不完整。
- Mem0 研究快照只投影记忆正文、ID 与变更类型；读文件前验证路径、大小及 SHA，额外 metadata 不自动显示。
- `semantics.py`：中文字段与常见标注解释；只解码展示容器，不修改来源事实。
- `view.template.html`：四个视角的共同界面；生成文件不直接编辑。

本地输出含原文，保持 Git 忽略；公开视图不自动混入私有轨迹。统计和评分的分母、粒度、来源版本必须明确。全部构建产物只是快照，不是实时系统状态。
