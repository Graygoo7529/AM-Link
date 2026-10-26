# AM-Link 二期重构实现

当前目录是二期重构的实验实现，版本 `0.2.1`。一期代码保存在
`archive/phase-1/`；重构前的二期实现保存在 `archive/phase-2/amlink-0.1.0/`。
AM-Link 只提供官方要求的 Add/Search，Search 返回证据，不生成最终答案。

**核心工程修复已实施，方法质量继续验证。** [核心审计](../docs/doing/2026-10-11-amlink-core-audit.md)保存0.2.0失败基线；[0.2.1修复报告](../docs/doing/2026-10-11-amlink-core-repairs.md)区分工程回归、真实小样本和待讨论的方法改进。尚未部署或参加官方 Smoke。

2026-10-23接入P0/P1：显式可见位置、精确多窗口、Inspect续页与回放保护、路径证据组、逐项Reflection依据、跨Add积累与冻结会话前缀。当前实现总览以[DESIGN](../DESIGN.md)为准；[实施核对](../docs/doing/2026-10-23-evidence-loop-implementation.md)保留工程测试、真实失败和方法限制。新工具接口不等于质量验收完成。

同日后续[闭环实施报告](../docs/doing/2026-10-23-reflection-convergence-implementation.md)：统一最终投影范围、恢复隐藏页读取、保留必要旧正文；数据库空旧范围可替代人物空Query，非法关系阻止整批提交，反馈随材料补齐更新。140项回归通过、220次新增真实调用；当前仍有Reflection协议/探索失败，未通过整体方法验收。Workspace内部格式v2，旧阅读凭据需重新取得；公开API和数据库版本不变。默认确定性装箱，离线LLM对照虽输出合法但漏掉一个来源。

2026-10-26：[最新实施报告](../docs/doing/2026-10-26-evidence-and-draft-implementation.md)记录窗口区分度/长度归一化、多来源预览、数值查询约束及可见来源回载。`AML2_REFLECTION_STAGED=true`可试验节点草案→关系→原子提交；默认false。阶段有明确准入，关系按端点类型约束，支持说明留到提交语境；无内部重试。小窗口已有构图成功，完整人物记录仍失败，不能据此切换默认或宣称整体验收。

## 核心边界

- 每个成功 Add 先保存不可变 `RawEvent`，再生成保留角色、会话、顺序、来源日期和原文的最小 `episode`，完成 BM25 与 embedding 索引。触发 Reflection 时，还要等待本请求目标水位内的全部批次终结才返回200；其他请求推进水位不能替代该请求的episode/索引检查。
- Add 可以先停在 `WorkingMemory`。达到条数/字符阈值、出现更新/遗忘信号或会话切换时，Reflection 才消费这一批工作记忆；同一用户的 Reflection 按水位串行。
- Reflection 的 context 由本批完整 WorkingMemory、持续保留的旧结构化节点和来源组成。模型可以 Query/Select（工具名 `reflection_search`）、Inspect、Backlink、Evict、Mutation 或真正 no-op；提交后保留Workspace，推进实际消费的批次水位。最低episode不可摘要覆盖，全部改变节点均同步嵌入。
- 标准 Search 每次创建独立语境，只检索结构化 `MemoryItem`（包括最小 episode），不读取 WorkingMemory，也不与 Reflection 共用 loop。Query 是 BM25+embedding（复杂问题可先做查询扩展），多个分支合并后统一 `select`；之后由模型决定 Inspect、Backlink 或停止，按深度/节点/邻居预算进行 BFS。
- `select` 同时筛选排序，不另设 `rerank`；输入仅question与自包含References，按大小分页后对保留候选统一精炼。Reference 预览保留互补来源片段、shown range 和省略原因；最终装箱按同一顺序做确定性证据闭合，逐来源记录 evidence units 和裁剪原因。受限 LLM 装箱只作为后续离线对照，不进入默认链路。
- 模型调用只尝试一次；依赖失败显式返回错误，不伪装为成功。官方调用方负责约定内重试。

默认本地总期限1740秒（Add含排队）、模型单次120秒、整包输入80000字符；Reflection每批32条/18000字符、最多64批，16轮含最后提交槽。普通积累需至少2个Add且达到8条/6000字符；容量为64条或36000序列化字符。Select每页24候选。阈值仍需质量校准；完整并发追加协调器未实现，仍使用同用户锁。配置见[.env.example](./.env.example)，旧库不会自动修复。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m py_compile (Get-ChildItem amlink -Filter *.py)
.\.venv\Scripts\python.exe -m pytest -q
```

在仓库根目录运行。根 `pytest.ini` 默认收集当前方法、靶场、数据层和可视化测试；只检查方法与靶场也可运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q amlink/tests benchmark/tests
```

根 `conftest.py` 为每次运行分配 `amlink/data/pytest-tmp/run-<唯一编号>/`，用于 `tmp_path`、测试数据库和 `.owner` 锁文件；缓存写入 `amlink/data/pytest-cache/`，均由现有 `data/` 规则忽略。独立目录避免并行测试互相清空，旧产物可按需清理，不能存放研究数据库。仍允许显式 `--basetemp`；若指定新路径，须先创建父目录，且 pytest 会清空该目录。不要再创建根目录 `.tmp-phase2-*`。标准库 `TemporaryDirectory` 仍使用系统临时目录。

需要真实模型时，使用被忽略的 `AML2_*` 环境变量，并通过靶场的
`--factory amlink.native:factory` 运行；不要把密钥写入代码、观测或报告。
接口字段和错误边界见 [PROTOCOL.md](PROTOCOL.md)，整体设计见根目录
[DESIGN.md](../DESIGN.md)。
