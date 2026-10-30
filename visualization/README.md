# AM-Link 研究可视化

2026-10-30：二期原始实验数据已按用户要求清理，旧运行入口不可再加载。历史案例、数据说明、研究综述和旧方法报告仍保留。当前方法见[第三版设计](../DESIGN.md)，真实结果见[实施核对](../docs/doing/2026-10-29-clean-rebuild-implementation.md)。

统一入口为 index.html；view.html 是同源会话片段。本地原文/轨迹只写入忽略的 data/local/，无需保存页面选择状态。

## 四个视角

1. 数据构成：下载范围、统计单位、原始/处理后的区别。
2. 样本与标注：历史、任务和评估侧字段；案例原文与标注分开。
3. 理论链路：Add → Search → Answer 所需的事实和来源，不冒充真实实现。
4. 运行观测：真实接口与模型调用、候选、筛选、原文交付和评注。

第三版增加导航笔记/原文链接、Select补查决定、最终顺序及装箱遗漏面板。笔记明确标为导航，不能当成已证实事实。长步骤输出优先保留首尾，完整artifact可从原档案读取。

## 加载

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --workspace --web
```

可重复传 --workspace-run 指定运行；--max-queries 与 --max-spans 控制网页投影数量，不改变完整档案。默认最近五个登记运行。构建不会调用收费模型。

[案例实验指南](../benchmark/STUDIES.md)说明按案例/切片/完整历史运行；[案例库](../casestudies/README.md)保留唯一catalog。新实验的数据库、trace、observability、源码快照和notes.jsonl位于忽略的 benchmark/data/runs。旧文档提到的r6/r11及Mem0原始轨迹已经清理，不能用那些路径构建当前观测。
