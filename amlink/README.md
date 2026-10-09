# AM-Link 二期方法

状态：**本地第一版 0.1.0 已实现**；有真实模型切片和 native 观测，尚未部署或参加官方 Smoke。效果与限制见[实施记录](../docs/doing/2026-10-08-amlink-implementation.md)。

`amlink/` 是二期实现的独立边界。只提供 Add/Search，主办方负责 Answer/Eval；`archive/phase-1/` 保持冻结。TinySoul-Agent 的缓存、引用、Reflection、Inspect/Search 思路用于设计参考，没有移植其完整 Agent 循环或 Jev。

面向讨论和后续更新的当前方法总览见仓库根目录 [`DESIGN.md`](../DESIGN.md)；本文件记录运行方式、当前参数和实现边界。

## 已实现的链路

```text
Add → 原文 + FTS + 幂等记录 → WorkingMemory 待整理视图
    → 达到阈值 / 更新信号 / 会话切换 → 加载相关旧记忆
    → 一次 gpt-4o-mini Reflection → 验证来源和 mutation
    → 原子提交节点、边、必要向量、处理位置 → 成功

Search → 原文/节点 BM25 + 可选 embedding → 候选 refs
       → Inspect 正向引用 + backlinks → 有界多跳
       → 可选模型选择 refs → 状态检查 + 来源证据装箱
```

统一节点支持 `episode/person/entity/concept/event/fact`；五种关系为 `about/contains/supersedes/contradicts/same_event_as`。`source_refs` 是来源真源，不另建重复的 derived_from 业务边。正文保留自然叙事，字段用于引用与校验。

每个模型操作只尝试一次。成功 Add 重放不调用模型；失败重放补做未完成阶段，已验证 mutation 与已完成向量批次落盘保存。未完成 Add 对该 user 的 Search 返回 425，后续不同 Add 返回 409。没有后台补偿、自动整用户重建或模型故障降级。

## 本地启动

在仓库根目录使用 Python 3.10+（当前验证环境是 3.13.14）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r amlink/requirements.txt
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink-v2.env
```

以 [.env.example](./.env.example) 为模板配置私有文件；仅识别 `AML2_` 前缀，不自动读取一期 Key。默认本机 `127.0.0.1:8080`、单进程、SQLite/WAL。命令行绑定非本机地址时必须配置鉴权。数据库与运行数据都位于被忽略的 `data/`。

无需模型的原文基线：

```powershell
$env:AML2_MODE = 'raw'
.\.venv\Scripts\python.exe -m amlink
```

`raw` 是显式实验模式，不是模型故障时的替代路径。端点为 `GET /health`、`POST /v1/memory/add`、`POST /v1/memory/search`；健康检查不试调用模型。请求和响应见 [PROTOCOL.md](./PROTOCOL.md)。

## 靶场和可视化

在已设置 `AML2_` 环境变量的 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe -m benchmark study --case lm4 --scope anchors --target native --factory amlink.native:factory --system-name AM-Link-v2 --system-version 0.1.0 --run-id amlink-lm4-my-run
```

run-id 每次使用新值。原文、SQLite、模型公开输出和观测进入 `benchmark/data/runs/<run-id>/`；自动注册研究工作区、更新 `visualization/data/local/index.html`。`amlink-method.json` 记录脱敏配置与源码哈希。可用 `--no-view` 批量完成后统一发布：

```powershell
.\.venv\Scripts\python.exe -m benchmark workspace publish
```

`--scope anchors` 由研究标注选择小切片，因此用于机制诊断，不能报告为全量准确率。模型只接收 Add 消息和 Search 问题；答案与评分标注留在靶场侧。HTTP 服务本身默认不采集内部轨迹，完整观测使用 native factory。

## 初始参数与边界

| 参数 | 默认行为 |
| --- | --- |
| Reflection | 待整理 8 条或 6000 字符触发；更新/遗忘线索和跨会话尾巴提前触发 |
| 单次 Add | 最多 128 消息、64000 字符；单条需适配 18000 字符窗口；超限明确 413 |
| 整理窗口 | 每批最多 32 条、18000 字符；当前 Add 最多 8 批 |
| 候选 | BM25 与可选余弦向量候选按倒数排名融合；64 个候选 |
| 图遍历 | 最多 3 跳、32 个新增节点、每入口 8 个邻居；0 跳可作对照 |
| 模型检索 | 复杂问题至多 1 次 query plan + 1 次 select；未选中的候选不进入结果 |
| 返回正文 | 每项 7000 字符，总计 24000 字符；截断与排除记录到观测 |
| embedding | 默认关闭；显式开启后为必需阶段，当前实验 embedding-3 / 512 维 |

这些数值是本地初值，不是比赛规格或经过容量校准的结论。原文通道使用词法检索，派生节点才建向量；未触发整理的最后几条可能缺少语义召回。日期保留原话，归一日期可缺一端，必须使用 YYYY-MM-DD；当前没有独立时间区间过滤器。

遗忘采用保守的**整条来源屏蔽**：屏蔽选中的原文和遗忘指令，失效依赖这些原文的节点及索引。其它独立原文保留；它不是数据库物理擦除，也没有证明对长历史的同义复述或全局撤回请求都能找齐。原始实验档案保留当时观测。

单数据库只允许一个进程持有写入权；user 内不排队，有界拒绝并发。向量检索当前线性扫描、高度节点的邻接枚举仍随数据量增长，暂不适用于未经验证的大规模部署。

## 代码与设计索引

| 文件 | 职责 |
| --- | --- |
| `schemas.py`、`config.py` | 输入协议、模型 mutation、显式预算与配置 |
| `store.py` | 隔离、幂等、事务、工作位置、FTS/向量、状态与撤回 |
| `reflection.py` | 自然叙事整理、ref/来源/关系校验 |
| `engine.py` | Add、候选发现、Inspect/backlinks、图展开和证据装箱 |
| `providers.py` | 无重试的真实模型接口、用量与费用未知值 |
| `api.py`、`__main__.py` | 本地 HTTP 服务与鉴权 |
| `native.py`、`observation.py` | 靶场接入、标准埋点和运行产物 |

设计阅读顺序：[MVP](./MVP.md) → [DESIGN](./DESIGN.md) → [PROTOCOL](./PROTOCOL.md) → [DISCUSSION](./DISCUSSION.md) → [PLAN](./PLAN.md)。设计文档中的目标不自动等于已实现功能，以本页和实施记录为准。

验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q amlink/tests benchmark/tests visualization/test_imports.py dataset/tests -p no:cacheprovider --basetemp amlink/data/pytest-local
```
