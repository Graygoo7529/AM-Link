# 2026-10-30 研究设施整合归档

用户确认把 benchmark、casestudies、visualization 整合为 research，dataset 独立。这里只保存历史，不是活动入口，不执行归档代码。

- `presentations/`：原两套页面、模板、生成器及旧研究汇总；已由 `research/web` 的唯一页面取代。
- `cases/`：二期运行阶段和Mem0历史方法报告；仍可作为历史经验查阅。
- `docs/doing/`、`docs/phase-2/`：过期执行方案与台账。原文的“当前”“下一步”仅对应历史日期。
- `docs/*-before.md`：本轮重写入口文档/项目记忆之前的副本。
- `data/runs/`：19份较早研究运行；`data/plans/`：旧准备计划；`data/presentations/`：旧生成页面。均被忽略，不恢复为新实验起点。
- `data/migration-before.json`：迁移前36245文件的路径、字节与SHA256；`data/migration-after.json`：迁移核对。活动登记的改写前副本单列保存。

原路径→当前路径：`benchmark/`→`research/benchmark/`，`casestudies/`→`research/cases/`，`visualization/`→`research/web/`；上述归档例外放在对应子目录。100题运行和 `clean30-hundred-answer` 冻结计划仍在活动研究目录，逐字节核验原始证据未变。

这是移动归档，没有永久清除实验原始材料。若在旧文档遇到不存在的相对链接，可据本映射定位；历史快照的路径字符串保持原样，以免伪造当时环境。
