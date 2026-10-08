# AM-Link 研究可视化

统一展示入口：[独立网页](./index.html)。`view.html` 是同源会话片段；原始样本与轨迹的本地扩展版在被忽略的 `data/local/`。原案例文档仍保留在 [`casestudies/`](../casestudies/README.md)。

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
