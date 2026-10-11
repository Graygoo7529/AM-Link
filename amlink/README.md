# AM-Link 二期重构实现

当前目录是二期重构的实验实现，版本 `0.2.1`。一期代码保存在
`archive/phase-1/`；重构前的二期实现保存在 `archive/phase-2/amlink-0.1.0/`。
AM-Link 只提供官方要求的 Add/Search，Search 返回证据，不生成最终答案。

**核心工程修复已实施，方法质量继续验证。** [核心审计](../docs/doing/2026-10-11-amlink-core-audit.md)保存0.2.0失败基线；[0.2.1修复报告](../docs/doing/2026-10-11-amlink-core-repairs.md)区分工程回归、真实小样本和待讨论的方法改进。尚未部署或参加官方 Smoke。

## 核心边界

- 每个成功 Add 先保存不可变 `RawEvent`，再生成保留角色、会话、顺序、来源日期和原文的最小 `episode`，完成 BM25 与 embedding 索引。触发 Reflection 时，还要等待本请求目标水位内的全部批次终结才返回200；其他请求推进水位不能替代该请求的episode/索引检查。
- Add 可以先停在 `WorkingMemory`。达到条数/字符阈值、出现更新/遗忘信号或会话切换时，Reflection 才消费这一批工作记忆；同一用户的 Reflection 按水位串行。
- Reflection 的 context 由本批完整 WorkingMemory、持续保留的旧结构化节点和来源组成。模型可以 Query/Select（工具名 `reflection_search`）、Inspect、Backlink、Evict、Mutation 或真正 no-op；提交后保留Workspace，推进实际消费的批次水位。最低episode不可摘要覆盖，全部改变节点均同步嵌入。
- 标准 Search 每次创建独立语境，只检索结构化 `MemoryItem`（包括最小 episode），不读取 WorkingMemory，也不与 Reflection 共用 loop。Query 是 BM25+embedding（复杂问题可先做查询扩展），多个分支合并后统一 `select`；之后由模型决定 Inspect、Backlink 或停止，按深度/节点/邻居预算进行 BFS。
- `select` 同时筛选排序，不另设 `rerank`；输入仅question与自包含References，按大小分页后对保留候选统一精炼。最终装箱保留该顺序、去重来源正文并输出日期；图新增候选目前追加在后，尚无最终证据闭包选择。
- 模型调用只尝试一次；依赖失败显式返回错误，不伪装为成功。官方调用方负责约定内重试。

默认本地总期限1740秒（Add含排队）、模型单次超时120秒、整包模型输入80000字符；Reflection每批最多32条完整消息/18000字符、最多64批。Select每页最多24候选。默认8条/6000字符的触发阈值尚待方法校准；完整并发追加协调器未实现，当前仍采用同用户锁。配置示例见[.env.example](./.env.example)。原0.2.0实验数据库不会自动修复或重建。

## 本地验证

```powershell
.\.venv\Scripts\python.exe -m py_compile (Get-ChildItem amlink -Filter *.py)
.\.venv\Scripts\python.exe -m pytest -q benchmark/tests
```

重构实现的本地回归也可运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q amlink/tests benchmark/tests
```

需要真实模型时，使用被忽略的 `AML2_*` 环境变量，并通过靶场的
`--factory amlink.native:factory` 运行；不要把密钥写入代码、观测或报告。
接口字段和错误边界见 [PROTOCOL.md](PROTOCOL.md)，整体设计见根目录
[DESIGN.md](../DESIGN.md)。
