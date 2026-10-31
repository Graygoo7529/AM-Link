# 记忆研究室

项目唯一研究入口：[打开研究页面](data/index.html)。它包含数据构成、字段与标注、41个理论案例、45个深入实测研究登记，以及旧百题基线与新轮真实问答和逐步观测。当前100个运行、309个问题条目包含重复轮次和失败，不能当309个独立样本或混合准确率。可以离线打开，不调用模型，也不保存页面选择状态。

最新[两组验证报告](../docs/doing/2026-10-30-intent-validation-findings.md)：96固定候选组件＋四类6历史24题配对，生产未改。两臂各168 Add/24 Search/24 Answer；新增[领养比较、排除已知主题、所指前文、新实例条件](cases/2026-10-30-intent-studies.md)四案例及八份绑定观测。新提示未证明稳定整体收益；中断3库单独保留，不入页面完整历史分母。

2026-10-30：原 `benchmark/`、`casestudies/`、`visualization/` 已整合到本目录。`dataset/` 独立负责数据读取与预处理；`amlink/` 独立负责参赛记忆方法。原100题仍是方法4191890的结果；新版本、运行身份和源码快照分别保存，不覆盖旧成绩。

最新[续读实施与真实核对](../docs/doing/2026-10-30-reading-continuation-implementation.md)：单一引用、连贯阅读块、未读候选续接已默认实施；六类18完整历史61题，新库555 Add全部返回，604/606整理。逐题研究复核40符合题意/9未达标/12不确定；25题另读证据。页面新增局部编号映射、阅读状态和增量说明，保留旧答案与旧评分。[新比赛日志案例](cases/2026-10-30-continuation-studies.md)说明“读到了仍没选齐”。研究Answer为GPT-5.4 medium，内部mini/v4不变。

## 使用与持续更新

此前[证据选择机制复核](../docs/phase-3/2026-10-30-selection-mechanism-review.md)重新检查77次Select：比赛关键事实在首轮已读，后续补查无增量；酒店用户偏好被排除，不能全部归因于Answer。案例与追加评注记录了更正；随后本轮两组实验保持独立运行身份。

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m research.web.build
```

构建会验证所有活动运行的计划、数据包、API轨迹、观测父子关系和材料哈希，生成 `research/data/index.html` 与按运行加载的 `runs/*.js`。请保留它们的相对位置。没有下载本地数据的另一台机器不能凭代码自动重建真实运行；原始数据与轨迹不会进入Git。

以后让助手“加载研究室”“分析这个案例”“更新本次运行”，都使用这里的案例身份和页面。普通浏览器可以直接打开；会话中可据同一份catalog与研究记录讲解。Codex浏览器连接器若限制真实原文访问，继续在本地文件中分析，不绕过访问审查。

- **新增理论案例**：编辑 [cases/catalog.json](cases/catalog.json)，绑定数据集、准备包、record/task/turn身份；写案例文档。唯一catalog同时服务实验取样和页面。
- **附真实研究**：在该案例 `studies` 中记录运行ID、数据包指纹、理论证据、实际断点、限制、下一实验。没有深入核对的题标为“尚未深入研究”，不自动生成假链路。
- **跑一个案例**：见 [research/benchmark/STUDIES.md](benchmark/STUDIES.md)。例如 `python -m research.benchmark study --case lm4 --scope full --target lexical` 是不调用模型的词法对照；真实AM-Link使用 `--target native --factory amlink.native:create_method` 并显式加载配置。
- **纳入已完成运行**：`python -m research.benchmark workspace register --run research/benchmark/data/runs/<id> --observations <该运行的observations文件>`。活动登记仍在忽略目录。无单独Answer时可只登记Add/Search。
- **添加批次汇总**：在 [workspace.json](workspace.json) 引用冻结计划目录；它只负责批次统计与复核，具体运行从活动登记读取，避免重复维护运行清单。
- **评注**：真实运行页可为本题/具体步骤下载带身份的评注JSON，再执行 `python -m research.benchmark workspace import-note --run research/benchmark/data/runs/<id> --file <评注文件>`。导入验证运行/数据/轨迹/步骤并追加，不能悄悄覆盖旧评注。

## 各目录只负责一件事

| 目录 | 职责 |
|---|---|
| `research/benchmark/` | 数据→Add/Search计划；方法适配；Answer/Eval；观测协议、活动运行与评注 |
| `cases/` | 具体案例、唯一catalog、理论链路、实测解释和改进议题 |
| `web/` | 展示代码与语义翻译；只读构建，不执行模型 |
| `data/` | 被忽略的唯一页面、运行展示分片和临时检查 |

旧页面、旧构建器、19份较早实验、旧计划及过期二期执行文档在 [研究归档](../archive/research/20261030-consolidation/README.md)。100题原库、原始响应、冻结计划和源码指纹保留，未重写。

## 当前结论

最新continuation轮工程与验证已完成，整体质量仍未验收；[计划核对](../docs/phase-3/2026-10-30-reading-continuation-execution.md)及[台账](../docs/doing/2026-10-30-reading-continuation-run-ledger.md)。以下数字保留为此前版本，不能和新版本混成一个提升率。

旧100题中，mini初评54正确/41未达标/5协议失败；Codex复核51正确/47未达标/2不确定。最新阅读改进r2六类12份历史38题：400/400 Add、36/38 Search、409/420整理；人工17正确/18未达标/3不确定。与旧版相同24题，正确13→11，尚无整体收益。两轮公开面板是同一38题，控制与失败单独计数；两种评分均非官方成绩，原文覆盖也不是答案准确率。

阅读 [最新实施核对](../docs/doing/2026-10-30-reading-contract-implementation.md)、[真实台账](../docs/doing/2026-10-30-reading-contract-run-ledger.md)、[原16个深入案例](cases/2026-10-30-real-evidence-studies.md)。catalog另追加9项新运行研究，保留原研究，不用新观察覆盖旧结论。本轮已实施原文锚点、真实邻接、导航分工、短段落Select、可见范围装箱和有限遗忘确认边界；剩余问题有具体断点，未宣布方法质量通过。

最新[根因复核与设计方向](../docs/phase-3/2026-10-30-mechanism-audit-and-directions.md)核对了160次Query、135次Select、732次Reflection；离线脚本和结果在忽略的 `data/mechanism30/`。它们解释原运行的机制，不是新模型实验或新准确率。网页“下一步设计”同步呈现这些方向。
