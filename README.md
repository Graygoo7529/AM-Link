# AM-Link

Graygoo7529 的原创记忆系统，面向 Agent Memory Leaderboard，只提供 Add/Search，由官方执行 Answer/Eval。

2026-10-30：第三版 `0.3.0-clean` 已完成六类26份完整历史、100题真实模型诊断；780 Add、100 Search、100 Answer均完成，Codex复核51正确/47未达标/2不确定，尚未部署或正式参赛。

- [方法设计与Add/Search](DESIGN.md) · [运行方法](amlink/README.md)
- [记忆研究室：唯一页面](research/data/index.html) · [如何加载与更新](research/README.md)
- [项目复盘与下一轮方法方案](docs/phase-3/2026-10-30-evidence-method-review.md)
- [100题实测报告](docs/doing/2026-10-30-hundred-answer-report.md) · [16个深入案例](research/cases/2026-10-30-real-evidence-studies.md)
- [原始数据与预处理](dataset/README.md) · [文档索引](docs/README.md)
- [一期](archive/phase-1/) · [二期r11](archive/phase-2/20261029-clean-rebuild/) · [研究整合归档](archive/research/20261030-consolidation/README.md)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -X utf8 -m research.web.build
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

模型固定gpt-4o-mini与text-embedding-v4/1024；无内部重试。显式加载私有配置，凭据不写入报告。实验数据、数据库和页面产物只在忽略目录。本轮整合benchmark/casestudies/visualization为research，不改变已经实测的方法算法或原始结果。
