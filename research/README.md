# 记忆研究室

项目唯一研究入口：[打开研究页面](data/index.html)。它包含数据构成、字段与标注、36个理论案例、16个深入实测研究，以及六类26份完整历史的100题真实问答与逐步观测。可以离线打开，不调用模型，也不保存页面选择状态。

2026-10-30：原 `research/benchmark/`、`research/cases/`、`research/web/` 已整合到本目录。`dataset/` 独立负责数据读取与预处理；`amlink/` 独立负责参赛记忆方法。本轮100题仍是原方法4191890的结果，未把研究页面改动记为新方法成绩。

## 使用与持续更新

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

100题中，mini初评54正确/41未达标/5协议失败；Codex复核51正确/47未达标/2不确定。两者分别呈现，均非官方成绩。原文覆盖也不是答案准确率。

阅读 [方法复盘与下一轮方案](../docs/phase-3/2026-10-30-evidence-method-review.md)、[16个深入案例](cases/2026-10-30-real-evidence-studies.md)、[整合计划](../docs/phase-3/2026-10-30-research-consolidation-plan.md)。本轮已经落地研究整合；遗忘回流、事件归属、候选覆盖和预算协同属于下一轮方法改进。
