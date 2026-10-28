# AM-Link 二期重构实现

2026-10-28最新：[工具协议与局部整理修订](../docs/doing/2026-10-28-tool-repair-implementation.md)已进入默认实现。统一schema验证与错误分层；evidence_positions区分撤销依据和持久支持；同组稳定编号，合法项检查点、受影响边重审、整组原子提交。286回归＋3子测试通过。16场景工具往返对照未达采用门槛，生产仅状态投影；真实质量以报告为准。新增运行依赖jsonschema，安装本目录requirements.txt。

2026-10-28：[节点保真与简明审查](../docs/doing/2026-10-28-memory-integrity-implementation.md)已进入默认方法。全部旧 episode/fact/event 正文与时间受保护；Reflection 不新建摘要 episode；可变导航节点仅继承当前支持；审查直接填写最终正文，校验时间原句/年份并提供具体修订反馈。258 回归＋3 子测试通过。最终三切片接口与来源成功，但 LM04 整理仅 1/3，复杂审查/图质量未验收。

当前目录是二期重构的实验实现，版本 `0.2.1`。一期代码保存在
`archive/phase-1/`；重构前的二期实现保存在 `archive/phase-2/amlink-0.1.0/`。
AM-Link 只提供官方要求的 Add/Search，Search 返回证据，不生成最终答案。

2026-10-28：默认 embedding 已迁移到智增增 `text-embedding-v4` / **1024 维**、批量最多 **10**；LLM 继续 `gpt-4o-mini`。旧模型环境变量会被拒绝，旧库向量指纹不兼容。已备份清理旧库，两个新库切片 6/6 Add、2/2 Search，回归 231 项＋3 子测试；长文本分段索引尚未实施，详见[迁移核对](../docs/doing/2026-10-28-embedding-v4-migration.md)。

**核心工程修复已实施，方法质量继续验证。** [核心审计](../docs/doing/2026-10-11-amlink-core-audit.md)保存0.2.0失败基线；[0.2.1修复报告](../docs/doing/2026-10-11-amlink-core-repairs.md)区分工程回归、真实小样本和待讨论的方法改进。尚未部署或参加官方 Smoke。

2026-10-27最新：[交付边界实施核对](../docs/doing/2026-10-27-delivery-contract-implementation.md)、[执行计划](../docs/phase-2/2026-10-27-add-search-contract-and-convergence-plan.md)。Add 可靠接收与 Reflection 进度独立；Search 可交付最后完成步骤的合法证据。当前数据库版本3，旧库显式拒绝，新实验必须新库。历史实现报告保留原始结论，当前流程以根 DESIGN 为准。

2026-10-23接入P0/P1：显式可见位置、精确多窗口、Inspect续页与回放保护、路径证据组、逐项Reflection依据、跨Add积累与冻结会话前缀。当前实现总览以[DESIGN](../DESIGN.md)为准；[实施核对](../docs/doing/2026-10-23-evidence-loop-implementation.md)保留工程测试、真实失败和方法限制。新工具接口不等于质量验收完成。

同日后续[闭环实施报告](../docs/doing/2026-10-23-reflection-convergence-implementation.md)：统一最终投影范围、恢复隐藏页读取、保留必要旧正文；数据库空旧范围可替代人物空Query，非法关系阻止整批提交，反馈随材料补齐更新。140项回归通过、220次新增真实调用；当前仍有Reflection协议/探索失败，未通过整体方法验收。Workspace内部格式v2，旧阅读凭据需重新取得；公开API和数据库版本不变。默认确定性装箱，离线LLM对照虽输出合法但漏掉一个来源。

此前同日阶段：[单一主链路实施报告](../docs/doing/2026-10-26-live-method-implementation.md)与[执行计划](../docs/phase-2/2026-10-26-live-method-plan.md)。该轮删除staged实验开关及旧整包提交，当前局部整理在此基础上继续实施。

## 核心边界

- Add 在模型准备完成后，用一个短事务提交原文、Working、不可变 episode、BM25/向量、必要遗忘屏蔽和成功凭据。必要接收失败本轮不生效；提交后的 Reflection 未完成不撤回接收结果。成功重放零模型调用。
- Reflection 按积累或会话边界触发，请求内有界执行。分组直接填写自然问题；逐组完成凭据允许后组先完成，保留版本有效的草案和待办，不重复相同失败输入。联合审查可以真正修改节点、撤销边，再补具体剩余工作。
- 标准 Search 每次独立语境，只查结构化 MemoryItem，包括最低 episode，不读 Working、不触发 Reflection。Query 分支合并后 Select，模型选择 Inspect/Backlink/Stop 多跳；每步完整成功后才合入语境。
- 首次 Query/必要 Select 失败仍失败；后续模型或协议失败记录局部停止，交付已有合法证据。存储/完整性失败不能伪装成功，无法装箱不能伪装正常空集。
- Select 以 question＋可读片段为输入，共用 80000 字符预算，按大小分页；不固定每 ref 四段。选中范围沿语境和装箱传递。确定性装箱去掉纯重复 episode 卡，路径不闭合时不输出该关系陈述。Search 始终不代答。
- 公开响应不增加整理状态字段；native 观测/网页分别展示接收、整理进度、内部错误与局部检索完成。HTTP 默认不采集内部轨迹。

默认请求期限1740秒（含Add排队），整理提前最多5秒收束；模型单次120秒、输入80000字符。Reflection规划批32条/18000字符、最多64批、每组16次主决策（含自动审查每页）；局部审查初审加最多两轮内容修订。普通积累至少2个Add且达到8条/6000字符；容量为64条或36000序列化字符。仍使用同用户串行锁，不新建后台队列、网络重试或隐藏降级开关。配置见[.env.example](./.env.example)。数据库3、冻结计划v3，旧库只读研究不作为新实验起点。

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
本机二期配置已保存在忽略的 `docs/private/amlink.env`；HTTP 启动显式使用 `python -m amlink --env-file docs/private/amlink.env`。靶场嵌入调用前用 `amlink.config.load_env_file` 加载同一文件，两个组件均显式提供智增增 Key；不要复用历史脚本绑定的 `ZHIPU_API_KEY`。仓库示例不含 Key，默认库是新建空库；测试与研究库各自独立。
接口字段和错误边界见 [PROTOCOL.md](PROTOCOL.md)，整体设计见根目录
[DESIGN.md](../DESIGN.md)。
