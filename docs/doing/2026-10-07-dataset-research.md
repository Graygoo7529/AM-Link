# 全量结构研究、案例扩充与本地对照

日期：2026-10-07。

## done：数据研究

对已下载 LongMemEval S/M/Oracle、CL-bench/Life、PersonaMem-v2 benchmark、BEAM 四档、MemoryAgentBench 四类和 PersonaMem-v3 samples 做了流式/逐批扫描，文件哈希重新匹配 receipt。原始统计在 `dataset/data/research/survey.json`，可发布聚合在 `visualization/research.json`；原文和运行记录不进入 Git。

| 来源 | 本轮核实的结构与用途 |
| --- | --- |
| LongMemEval | 同一批 500 题；30 拒答。6 类问题；S 每题会话中位数 48，Oracle 2；证据标记含 54 个 assistant turns |
| CL-bench | 1,899 任务，500 context_id，4 类/18 子类；31,607 rubric 条目。621 条可按现有规则拆分，1,278 条保持原输入 |
| CL-bench Life | 405 任务，3 类/9 子类；5,348 rubric；现有规则可拆分全部任务，但未运行完整评分 |
| PersonaMem-v2 | 5,000 题/200 人；522 他人信息，1,048 ask_to_forget，511 sensitive_info；这些标注轴并不互斥 |
| BEAM | 三档 90 条＋10M 10 条，每条 20 probes，共 2,000 probes。10M 的 chat 是不同的多层嵌套 |
| MemoryAgentBench | 146 context/3,671 questions：检索 2,000；冲突 800；长理解 171；测试时学习 700 |
| PersonaMem-v3 | 100 人，221,817 事件，15,791 问题，31 任务类型；顶层与嵌套生成标签需隔离 |

## done：处理与案例

- 修复 LongMemEval 原始日期解析，保留 source_date 和无时区归一化假设；原 pack 毫秒约定不变。
- 构建 5 个独立研究 pack：LongMemEval 三题完整 S 历史、PersonaMem-v2 两人完整 32K 历史、MAB 一题完整 455 事实、PersonaMem-v3 两题严格时间切片，以及单独的 6 条件短片段实验包。
- PersonaMem-v3 除时间/用户隔离外，删除 `conversation_json` 内部 `embeds_pref_idx` 等标签及作者 `interaction_type` 分类；保留原 action 和独立 `user_message` 的记忆限制。
- 案例库 8 → 16：新增 LM01–03、PV01–02、M01、V301–02；与可视化共用唯一 catalog。
- 可视化加入全量构成条形图、原始字段分流、三跳路径、本地检索结果、五阶段设计检查；网页与会话片段同源。

## done：实际本地 BM25 对照

完整 LongMemEval-S 每道题独立索引其原始 turns；k1=1.2、b=0.75，简单英文正则分词与固定停用词；不改写、不词干化、不调用模型。Gold 只在排名完成后用于匹配。

| 题型 | 可回答题分母 | 任一证据 @5 | 完整证据 @5 | 完整证据 @10 |
| --- | ---: | ---: | ---: | ---: |
| 更新 | 72 | 66 | 52 | 60 |
| 跨会话 | 121 | 93 | 29 | 55 |
| 单会话助手 | 56 | 48 | 48 | 51 |
| 单会话偏好 | 30 | 12 | 7 | 11 |
| 单会话用户 | 64 | 57 | 57 | 61 |
| 时间 | 127 | 97 | 69 | 90 |
| 总计 | 470 | 373 | 262 | 328 |

“完整”指作者标记的不同证据正文全部命中；相同正文的重复标记去重。30 道拒答不进入分母；本轮没有无标注的可回答题。它不是语义覆盖认证或 QA 成绩，其他未标记来源也可能支持答案。

M01 对完整 455 事实做相同检索：top-5 包含 fact-107 和 fact-146（旧/新作者），不含 fact-335 和 fact-322（最新配偶/国籍）。这是直接可见的路径缺口，未执行回答模型。

## Mem0 探索状态

已在忽略的 `benchmark/data/research-env` 安装 Mem0 2.2.1、pyarrow 25.0.1 等；未更改根虚拟环境。六条件实验使用已有 observability v1 记录实际调用、写入后快照与答案。

首次联网执行因具体数据与目的地授权被自动审批阻止；用户随后明确允许，已完成 run `mem0-microstudy-20261007`。41 次模型请求、371,647 输入字符，均在 100 次/50 万字符边界内；0 请求失败，费用未知。时间两条件失败、更新与拒答本例正确；他人信息未错归但 Answer 过度拒绝，遗忘例没有激活真正删除。详见[逐例实测报告](../../casestudies/mem0-microstudy.md)。不汇总为总体准确率，不把 BM25 结果当作 Mem0 结果。

验证：数据层 22、靶场 20、展示/案例 8 项测试；公开/本地构建一致性与浏览器交互检查。原文、快照、模型日志和数据库均留在忽略目录；本轮未提交或推送。

## 重建

使用安装了 `benchmark/requirements-research.txt` 的隔离环境执行：

```powershell
python -m dataset.survey --include-m
python -m dataset.research_cases
python -m benchmark.lexical_study
python -m visualization.research
python -m casestudies.build --web
python -m visualization.build --web
python -m visualization.build --local --web
```

`dataset.survey` 与 pack 构建不调用模型；`benchmark.microstudy` 是必须显式执行的联网实验。导入实际运行仍使用 visualization.build 的 `--run / --run-kind / --observations`，不把理论分析补进实测轨迹。
