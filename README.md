# AM-Link

Graygoo7529 的原创记忆系统，面向 Agent Memory Leaderboard，只提供 Add/Search，由官方执行 Answer/Eval。

2026-10-31：`0.3.4-continuity`已按固定提交`1f91365`部署，已收敛可读引用、跨轮阅读记录、原文闭合与预算观测；不稳定的区间裁剪协议已撤回。生产只提供 Add/Search；公开百题主路径780/780 Add、100/100 Search通过，最终源码另做三类完整历史验证。接口完成不等于答案正确。

- [本轮实施与计划核对](docs/doing/2026-10-31-continuity-budget-implementation.md) · [执行计划](docs/phase-3/2026-10-31-continuity-budget-execution-plan.md)
- [服务器部署与发布包](deploy/README.md) · [实际部署与接口清单](docs/doing/2026-10-31-server-deployment.md)：HTTPS、真实mini/v4、16路合成并发、重启持久性通过；尚未提交官方评测。

- [方法设计与Add/Search](DESIGN.md) · [运行方法](amlink/README.md)
- [此前：96组件＋24题配对真实验证](docs/doing/2026-10-30-intent-validation-findings.md) · [所指前文、排除意图与新实例案例](research/cases/2026-10-30-intent-studies.md)。本轮提示变化未证明整体收益，生产未改。
- [记忆研究室：唯一页面](research/data/index.html) · [如何加载与更新](research/README.md)
- [项目复盘与下一轮方法方案](docs/phase-3/2026-10-30-evidence-method-review.md)
- [根因复核](docs/phase-3/2026-10-30-mechanism-audit-and-directions.md) · [改进执行计划](docs/phase-3/2026-10-30-reading-contract-execution-plan.md)
- [100题实测报告](docs/doing/2026-10-30-hundred-answer-report.md) · [16个深入案例](research/cases/2026-10-30-real-evidence-studies.md)
- [此前：续读改进执行计划与核对](docs/phase-3/2026-10-30-reading-continuation-execution.md) · [读到却没选齐：新案例研究](research/cases/2026-10-30-continuation-studies.md)
- [此前：模型叙事实测与更强Answer](docs/doing/2026-10-30-narrative-and-answer-findings.md)
- [原始数据与预处理](dataset/README.md) · [文档索引](docs/README.md)
- [一期](archive/phase-1/) · [二期r11](archive/phase-2/20261029-clean-rebuild/) · [研究整合归档](archive/research/20261030-consolidation/README.md)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -m research.web.build
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

参赛方法模型固定gpt-4o-mini与text-embedding-v4/1024；研究侧Answer默认GPT-5.4 medium，和官方Answer型号无关。无内部重试。显式加载私有配置，凭据不写入报告。实验数据、数据库和页面产物只在忽略目录。benchmark/casestudies/visualization已统一为research；后续方法修改另立源码快照与实验身份，不覆盖历史原始结果。
