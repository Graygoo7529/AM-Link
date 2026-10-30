# 数据集与本地靶场主计划

创建：2026-10-04；更新：2026-10-05。数据层解耦和本地靶场基础能力 `done`；数据扩充与真实目标对照 `in_progress`。

## 整体要求

1. 从作者或维护者公开发布源获取数据，不要求与比赛专用版本关联；登记原始文件、许可、版本、实际获取范围与处理方法。
2. dataset 只负责数据读取、分析、预处理、选择和切分，产出中立历史/任务/标注；数据集不绑定评测方法或对象。
3. benchmark 一侧将数据构建成可重复环境，另一侧用官方风格 Add/Search 适配 AM-Link、Mem0 等对象。数据环境策略可以根据数据特点设计，不假定它必须照搬官方数据处理。
4. 正式机会有限，先在本地小样本反复检验；保留请求、响应、原始来源、排名、错误和可核对的归因。
5. 不获取开源对照框架源码构建；优先已发布的 Mem0 包或可直接访问的 API。本地不使用 Docker。

## 当前方案与状态

`原始数据 → dataset pack → benchmark 环境计划 → target Add/Search → trace/report`。

| 状态 | 工作 | 产物与验收 |
| --- | --- | --- |
| done | 第一轮来源与接口调研 | [初版来源调查](./2026-10-04-dataset-research.md)、[初版靶场](./2026-10-04-benchmark-arena.md)，作为历史记录 |
| done | 按用户语义重构数据与靶场 | [2026-10-05 设计、下载与核验](./2026-10-05-dataset-decoupling.md)，取代初版 dataset 直接生成 manifest 的设计 |
| done | 数据获取与基础方法 | [dataset 使用说明](../../dataset/README.md)：原始文件/行快照、读取、统计、切片、分组 split、来源 pack |
| done | 双向适配和可观测性 | [benchmark 使用说明](../../benchmark/README.md)：离线 plan、目标接口、逐请求 trace、source 追溯、指标与边界 |
| done | 真实小片管线验收 | 5 份数据环境计划；临时 HTTP 对象完成 5 Add/3 Search 和 inspect；不计作真实方法效果 |
| pending_external | 获取受网络影响的材料 | LongMemEval S/Oracle 文件 502、rows 500；PersonaMem 历史 502。已保留入口与明确状态 |
| pending_target | AM-Link/Mem0 真实对照 | 二期服务尚未实现；Mem0 尚未安装/配置；不能报告未运行的分数或模型费用 |
| todo | 答案级与更多环境策略 | 固定 Answer/Eval 配置、记录预算后扩展；增量检查点与干扰历史均在 benchmark 层实现 |

## 当前已获取范围

LoCoMo 原版与 Refined 的完整对话/QA、ScriptMem 全部公开 QA；CL-bench 和 Life 各 3 条无截断快照；PersonaMem-v2 文本题 3 条；BEAM 100K split 一个完整对话。所有原始/派生材料保留在 Git 忽略的数据目录，来源和 SHA 在 catalog/receipt 中。

## 核对原则

标注答案、rubric、偏好不得混入历史写入；缺少历史不合成替代；缺少 evidence 不冒充零分或空检索题。先看实际请求与响应，再解释错误；接口未提供的模型 usage/cost 为 null。字面证据匹配不是答案质量或官方成绩。

每次比较固定 pack、profile、选择条件、对象版本和独立 run namespace。提交只包含代码、清单与文档，不含数据/trace、凭据或数据库。完成后运行相应测试、Git 状态和 diff 空白检查；不自动提交或推送。
