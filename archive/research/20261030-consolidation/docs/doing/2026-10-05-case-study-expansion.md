# 案例库与数据扩充

日期：2026-10-05；本轮案例记录、公开下载、处理与检查 `done`。未完成的数据源逐项保留实际状态。

## 已完成

- 新建 `casestudies/`（本轮后迁至根目录）：索引、模板、数据地图，记录 L01–L03、P01/P02、B01/B02、C01 八个分析案例；明确设计示意与实测边界。
- 下载固定 PerLTQA commit 的中文 memory/QA、LICENSE、README，Git blob hash 与 SHA-256 校验，原文保存到忽略目录。141 个人物记忆，QA 覆盖 32 人、8,593 题。
- 实现 `dataset/perltqa.py` 及 CLI 接入：双输入哈希、来源单元、人物归属、引用检查、答案/anchors 隔离、无效引用排除记录。不自动修复来源矛盾，不将资料分区叫作真实聊天。
- 取得 CL-bench Life offset 100 起两条及 BEAM `100K` offset 1 一条；均为无截断 HF 行快照。已有样本不覆盖。
- 更新目录、数据层说明与来源清单。PerLTQA 原始数据、派生 pack/plan、下载回执均不进入 Git。

## 已核对的本地处理结果

| 产物 | 记录 | 历史单元 | 任务 | 实验计划 |
| --- | ---: | ---: | ---: | --- |
| `dataset/data/prepared/perltqa-zh-full.json` | 32 人 | 2,211 文档单元 | 8,593 | 仅准备，不执行目标 |
| `dataset/data/prepared/perltqa-zh-cases.json` | 2 人 | 139 文档单元 | 444 | 14 Add、444 Search；作者来源文档级 evidence 可解析 |
| `dataset/data/prepared/beam-update-cases.json` | 1 对话 | 200 发言 | 20 | 37 Add、20 Search；当前未评分 |
| `dataset/data/prepared/clbench-life-extra.json` | 2 记录 | 7 消息 | 2 | 9 Add、2 Search；当前未评分 |

plan 位于 `benchmark/data/plans/`，是离线构造，未发送给 AM-Link/Mem0。中文 Add 的空白分词是现有本地近似，不是 token 计数或官方上限认证。

## 新发现与待解决

- `pending_external`：LongMemEval Oracle 文件 502、S 行接口 500；未保留残片。M/10M 本轮未取。
- `pending_external`：PersonaMem-v2 history 相对路径应落在作者 HF 数据仓库；当前 GitHub 代码仓库不存在该历史。正确 HF pinned 文件仍 502；任务包仍缺历史。
- `pending_external`：MemoryAgentBench 的 splits 接口可读，CR/TTL 单条 row 读取超时；来源已登记，无可用本地快照。四类任务与 PersonaMem-v3 的跨平台数据作为后续候选。
- `todo`：PerLTQA 全量标注质量审查；P02 发现对话日期、事件日期与答案冲突。全部 reference 可解析不能保证 gold 答案正确。
- `todo`：PerLTQA 人物之间共享实体/经历关系复核；不能直接宣称按人物划分即完全独立。
- `todo`：BEAM 的 source_chat_ids 到真实 turn 的统一、逐题核验映射。本轮只人工核对案例来源，不扩大为全量 gold evidence。
- `todo`：真实系统实验与统一 Answer/Eval，当前没有记忆质量提升、运行延迟或模型费用结论。

## 验证

数据层 14 项、靶场 16 项测试通过；新增测试检查双输入回执、悬空引用、答案/anchors 不进入 Add。真实数据完成 pack → plan 检查；18 份 acquisition receipt 逐个复算 SHA 一致，无 `.partial`。PerLTQA 的 8,593 题来源引用均可解析，但未核验全部字符 anchors 或答案事实。

对话内交互展示覆盖本地数据状态、原始/处理后特点与八个案例；检查了数据集/案例切换、缺历史状态及 736/360 像素布局。展示仅为人工方法分析，不是实际系统 trace。

本轮未读取私有 Key、未调用收费模型、未安装依赖/Docker、未操作服务器、未提交或推送。未提交范围为案例与索引文档、PerLTQA 读取代码/测试和来源清单配置；无一期归档删除或部署配置变更。
