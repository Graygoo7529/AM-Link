# AM-Link 二期重构实现

当前目录是二期重构的实验实现，版本 `0.2.0`。一期代码保存在
`archive/phase-1/`；重构前的二期实现保存在 `archive/phase-2/amlink-0.1.0/`。
AM-Link 只提供官方要求的 Add/Search，Search 返回证据，不生成最终答案。

## 核心边界

- 每个成功 Add 先保存不可变 `RawEvent`，再生成一个保留角色、会话、顺序和原文的最小 `episode`，并完成 BM25 与 embedding 索引后才返回 200。
- Add 可以先停在 `WorkingMemory`。达到条数/字符阈值、出现更新/遗忘信号或会话切换时，Reflection 才消费这一批工作记忆；同一用户的 Reflection 按水位串行。
- Reflection 的 context 由新 WorkingMemory、旧结构化节点和来源组成。模型通过工具调用决定继续 `Search`、`Evict`、提交 Mutation 或停止；Mutation 经过来源、类型、时间和关系校验后原子提交。
- 标准 Search 每次创建独立语境，只检索结构化 `MemoryItem`（包括最小 episode），不读取 WorkingMemory，也不与 Reflection 共用 loop。Query 是 BM25+embedding（复杂问题可先做查询扩展），多个分支合并后统一 `select`；之后由模型决定 Inspect、Backlink 或停止，按深度/节点/邻居预算进行 BFS。
- `select` 同时承担候选精炼和排序，不另设 `rerank`。模型可见 References 同时包含语义化 ref 与命中叙事、来源和关系信息。
- 模型调用只尝试一次；依赖失败显式返回错误，不伪装为成功。官方调用方负责约定内重试。

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
