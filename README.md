# AM-Link

Graygoo7529 的原创记忆系统，面向 Agent Memory Leaderboard，只提供 Add/Search，由官方执行 Answer/Eval。

2026-10-30：当前方法 `0.3.2-continuation` 已实施单一引用、连贯原文阅读块和未读候选续读；六类18完整历史555/555 Add、61/61 Search/Answer、604/606整理。真实效果与限制见[实施核对](docs/doing/2026-10-30-reading-continuation-implementation.md)和[台账](docs/doing/2026-10-30-reading-continuation-run-ledger.md)。接口完成不代表回答全对；尚未部署或正式参赛。

- [方法设计与Add/Search](DESIGN.md) · [运行方法](amlink/README.md)
- [最新：96组件＋24题配对真实验证](docs/doing/2026-10-30-intent-validation-findings.md) · [所指前文、排除意图与新实例案例](research/cases/2026-10-30-intent-studies.md)。本轮提示变化未证明整体收益，生产未改。
- [记忆研究室：唯一页面](research/data/index.html) · [如何加载与更新](research/README.md)
- [项目复盘与下一轮方法方案](docs/phase-3/2026-10-30-evidence-method-review.md)
- [根因复核](docs/phase-3/2026-10-30-mechanism-audit-and-directions.md) · [改进执行计划](docs/phase-3/2026-10-30-reading-contract-execution-plan.md)
- [100题实测报告](docs/doing/2026-10-30-hundred-answer-report.md) · [16个深入案例](research/cases/2026-10-30-real-evidence-studies.md)
- [最新：续读改进执行计划与核对](docs/phase-3/2026-10-30-reading-continuation-execution.md) · [读到却没选齐：新案例研究](research/cases/2026-10-30-continuation-studies.md)
- [此前：模型叙事实测与更强Answer](docs/doing/2026-10-30-narrative-and-answer-findings.md)
- [原始数据与预处理](dataset/README.md) · [文档索引](docs/README.md)
- [一期](archive/phase-1/) · [二期r11](archive/phase-2/20261029-clean-rebuild/) · [研究整合归档](archive/research/20261030-consolidation/README.md)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -m research.web.build
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

参赛方法模型固定gpt-4o-mini与text-embedding-v4/1024；研究侧Answer默认GPT-5.4 medium，和官方Answer型号无关。无内部重试。显式加载私有配置，凭据不写入报告。实验数据、数据库和页面产物只在忽略目录。benchmark/casestudies/visualization已统一为research；后续方法修改另立源码快照与实验身份，不覆盖历史原始结果。
