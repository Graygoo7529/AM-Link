# AM-Link 二期实现与首次验证

日期：2026-10-08。状态：**done（本地 0.1.0、靶场接入与有限真实切片）**。尚未部署、未参加官方 Smoke；建图质量、规模与费用校准继续研究。

## 实现范围

`amlink/` 现在包含可运行的 Add/Search 服务：原文真源、幂等和 user 隔离、WorkingMemory 待整理区、统一 MemoryItem、Reflection mutation 校验、Inspect/backlinks、多跳展开、BM25/embedding 候选、状态与来源屏蔽、无内部重试的模型接口、FastAPI、本地 native 观测。入口和命令见 [amlink/README.md](../../amlink/README.md)。

TinySoul 的影响集中在“先缓存再整理、ref 是内容地址、Inspect 精确读已知 ref、Search 发现与选择”的分工。AM-Link 没有搬入其完整 Agent 循环、Jev 或日历驱动后台任务；连续会话通过处理位置和阈值组织，缺少日期就保留未知。

- 未触发 Reflection 时，原文已进入 FTS 即可成功；触发的必要整理/向量失败则返回错误。
- 成功请求重放不调用模型；失败重放复用已持久化 context、验证后的 mutation 和完成的向量批次。
- 原文与派生提交分阶段；未完成 Add 期间该 user 的 Search 返回 425，另一 Add 返回 409。其他 user 不读取其数据。
- 请求内每个模型操作只尝试一次，没有 SDK 重试、自动修复请求或后台补偿。开发期间的多次运行是改代码后的显式独立实验，均保留档案。
- 自然语言正文解释事实，少量字段和边维持引用边界。代码字段为 `ref/source_refs`，对应设计文档的 `memory_id/source_event_ids`。
- `daily` 是可知日期下的 episode 视图，不增加一套表。`person/entity/concept` 共用节点表；没有强制每条输入生成六类节点。

内部规范化仅处理可确定的表示差异：节点到已加载 raw 的 about/contains 归入来源；fact/event → contains → episode 调整为日志包含事实的方向；正文、类型、时间完全相同且保留旧来源的新节点复用旧 ref。未知来源、重复临时标签、事实正文覆盖和不合法边仍会失败。这些检查不能证明模型叙事正确。

## 离线验证

**91 项测试通过**，覆盖新方法、现有靶场、数据适配和可视化导入：

```powershell
.\.venv\Scripts\python.exe -m pytest -q amlink/tests benchmark/tests visualization/test_imports.py dataset/tests -p no:cacheprovider --basetemp amlink/data/pytest-local
```

重点包括：立即检索、持久化重启、跨用户隔离、请求冲突、成功幂等、失败阶段恢复、无模型重试、WorkingMemory 时序、两跳正向/反向检索、深度与节点预算、连续更新、三方冲突、同批助手遗忘回声、日期部分未知、模型选空、HTTP 契约和鉴权，以及 native 模型输出能进入既有可视化。

一项 FastAPI/Starlette 对 httpx 测试客户端的弃用提示不影响通过。测试临时目录重用曾遇到 Windows 权限限制，改用新的忽略目录后通过；未把环境错误作为方法失败。

## 真实模型切片

授权目的地为现有 gpt-4o-mini 与 embedding-3 接口。设置 Reflection threshold=1、embedding 开启，便于小切片观察；这不同于默认的 8 条阈值。以下为开发迭代中的代表运行，不是固定版本的正式 A/B 实验。

| 案例 / run 后缀 | Add / Search | 证据或方法观察 | 模型调用 | Search 延迟 |
| --- | --- | --- | ---: | ---: |
| LM04 / `lm4-20261008-g` | 4/4、1/1 | @5 来源覆盖 4/4；raw 基线也是 4/4 | 6 LLM + 8 embedding | 4.28 s |
| LM05 / `lm5-20261008-a` | 2/2、1/1 | 分子/分母 2/2；raw 也是 2/2 | 2 LLM + 4 embedding | 0.23 s |
| BEAM B02 / `b2-20261008-b` | 1/1、1/1 | 两个矛盾 fact 都返回，但未建立 contradicts 边 | 1 LLM + 2 embedding | 0.19 s |
| LoCoMo L04 / `l4-20261008-c` | 5/5、1/1 | @5 来源覆盖 7/7；同样适配器的 raw 为 5/7 | 5 LLM + 8 embedding | 0.30 s |
| 遗忘短例 / `forget-20261008-b` | 2/2、1/1 | 明确偏好回声被屏蔽，旧园艺建议仍返回；不判完整通过 | 4 LLM | 3.55 s |

完整 ID 均以 `amlink-v2-` 开头。五个 raw 对照运行以 `amlink-raw-<case>-20261008` 命名。B02 与遗忘短例未绑定可评分的 gold evidence，不能填入推测的正确率。

整个开发过程保留 **15 份真实调用档案、83 次模型调用尝试**，其中一次网络失败没有 token 用量。其余返回的用量合计为 input 71,284、output 8,245 tokens；这是已报告用量，未知失败不计作 0。未取得价格账单，费用为未知，不把估算当实付。另有 5 份零模型 raw 运行。

早期失败档案保留了日期格式不一致、原文引用位置、重复临时标签、contains 类型/方向等问题。来源和协议修复后重跑成功，不删除失败或把它们混入成功率分母形成全量结论。

## 三个必须区分的结果

**来源召回齐了，不等于图起效。** L04 成功运行实际只有 2 个 episode、1 个 fact，0 条业务边；人物名和两侧原文已返回，但模型尚未稳定建立 person/concept 图。此次 @5 改善来自叙事、来源组合和候选排序，不能说多跳已改善真实效果。两跳原语只在确定性构造测试中得到验证。B02 同样保留了两端事实，却没有结构化冲突关系；top-1 仍可能只返回一端。

**输入身份不能在适配层丢掉。** 原适配器把 Joanna/Nate 转成 user/assistant 后未传原名，模型据此生成“用户/助手”的记忆。`evidence-retrieval-v2` 现在为每个显式 speaker 加 `Speaker: <原名>` 前缀，同时计入分块预算；原文 offset 和 evidence 判定仍使用未加前缀的来源片段。旧档案不自动改写。L04 后续运行同时调整了提示和去重，不能把所有变化都归因于前缀。

**HTTP 成功不能证明遗忘完整。** 首次遗忘运行只屏蔽指令，助手“我会忘记你喜欢园艺”的复述仍被返回。修改提示后，遗忘指令与确认消息共 2 条来源被屏蔽，但更早的园艺建议仍存在。它不是用户偏好的证据，却可能继续影响 Answer。这里需要后续区分“删除偏好断言”和“避免受其影响的建议”；当前未运行 Answer，也没有声称此问题已解决。

## 运行观测与复用

已保存 8 条持久评注，分别绑定具体 run/search/stage。网页当前加载上表五份代表运行：

- [本地运行可视化](../../visualization/data/local/index.html)
- [工作区运行清单](../../benchmark/data/research/workspace.json)
- 每份运行保存 report、trace、observability、公开模型产物和脱敏配置；后期运行及今后的运行还记录源码哈希。

普通重载：`python -m visualization.build --local --workspace --web`。默认只加载最近五份登记运行；用重复的 `--workspace-run <id>` 指定需要比较的档案，不需要再请求模型。原始数据、SQLite、产物和评注均留在忽略目录。

## 后续工作边界

1. 用固定输入、固定 Add 产物对比 0/1/3 跳，再评估是否真正补足人物、冲突和多事件证据。
2. 提示与校验仍可能拒绝不合法 mutation；边界测试通过不代表 gpt-4o-mini 输出协议已稳定。优先观察节点身份、来源错绑、漏边和错误合并。
3. 原文仅词法召回，待整理尾部尚无向量；query plan 的复杂度启发式也可能漏掉实际复杂问题。二者要单独做消融。
4. 时间原话与可选日历日期已保存，未实现独立区间过滤、事实有效期或完备时间推理。正文预算当前用字符近似 token。
5. 整条来源屏蔽会连带隐藏该消息中的其它信息，并失效依赖它的节点；不等于物理擦除、全局同义遗忘或完善隐私策略。
6. 目前单进程 SQLite，向量线性扫描，高连接节点的邻接枚举未做数据库分页；容量、并发、长历史和官方 Smoke 留待下一阶段。本轮未操作服务器。
