# AM-Link

Graygoo7529 的原创记忆系统，面向 Agent Memory Leaderboard，只提供 Add/Search，由官方执行 Answer/Eval。

2026-10-30：当前为第三版 `0.3.0-clean`。以“不可变原文＋导航笔记＋有界证据检索”重建，二期 r11 的复杂图修改流程已归档。工程检查与真实质量分开记录，尚未部署或正式参赛。

- [设计与 Add/Search 流程](DESIGN.md)
- [重构执行计划](docs/phase-3/2026-10-29-clean-rebuild-plan.md)
- [实施和验证结果](docs/doing/2026-10-29-clean-rebuild-implementation.md)
- [运行方法](amlink/README.md)
- [数据集](dataset/README.md) · [案例库](casestudies/README.md) · [靶场](benchmark/README.md) · [可视化](visualization/README.md)
- [一期归档](archive/phase-1/) · [二期 r11 归档](archive/phase-2/20261029-clean-rebuild/)

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

模型固定 `gpt-4o-mini` 与 `text-embedding-v4`/1024维。必须配置两者；无内部重试。明确加载的旧私有文件可将受支持的 AML2 字段映射到 AML3，凭据不写入报告。旧实验数据已清理；历史台账保留，不代表原始运行库仍存在。
