# 文档入口

当前方法为第三版 `0.3.4-continuity`；研究设施已统一为 [research](../research/README.md)。

最新：[连续检索与稳定版本实施核对](doing/2026-10-31-continuity-budget-implementation.md)、[执行计划](phase-3/2026-10-31-continuity-budget-execution-plan.md)、[部署说明](../deploy/README.md)。最终发布包与历史实验使用不同源码身份，工程完成不代表语义质量通过。下方是此前阶段记录。

1. [方法设计与Add/Search](../DESIGN.md)
   · [此前：两组真实验证与后续方向](doing/2026-10-30-intent-validation-findings.md)、[执行计划核对](phase-3/2026-10-30-intent-validation-plan.md)、[成本与中断台账](doing/2026-10-30-intent-validation-ledger.md)、[四个新案例](../research/cases/2026-10-30-intent-studies.md)；提示对照未证明稳定整体收益，生产未改。
   · [此前分析：从主题相关到回答所需的证据选择](phase-3/2026-10-30-selection-mechanism-review.md)（只读复核、轨迹更正与待讨论方向）
   · [此前：续读实施核对](doing/2026-10-30-reading-continuation-implementation.md)、[执行计划](phase-3/2026-10-30-reading-continuation-execution.md)、[运行台账](doing/2026-10-30-reading-continuation-run-ledger.md)
   · [多部分日志与集合选择案例](../research/cases/2026-10-30-continuation-studies.md)
   · [此前：自然叙事实测、强Answer与后续设计](doing/2026-10-30-narrative-and-answer-findings.md)、[执行与后续计划](phase-3/2026-10-30-narrative-and-answer-plan.md)
   · [本轮阅读改进计划](phase-3/2026-10-30-reading-contract-execution-plan.md)、[实施核对](doing/2026-10-30-reading-contract-implementation.md)、[真实运行台账](doing/2026-10-30-reading-contract-run-ledger.md)
   · [Add→Search→Answer失败归因与强模型对照](doing/2026-10-30-add-search-answer-diagnosis.md)
2. [100题真实测试报告](doing/2026-10-30-hundred-answer-report.md)与[运行台账](doing/2026-10-30-hundred-answer-ledger.md)
3. [项目复盘与下一轮方法设计](phase-3/2026-10-30-evidence-method-review.md)
   · [此前：模块语义、根因复核与改进方向](phase-3/2026-10-30-mechanism-audit-and-directions.md)
4. [研究整合计划](phase-3/2026-10-30-research-consolidation-plan.md)与[实施核对](doing/2026-10-30-research-consolidation-implementation.md)
5. [16个深入案例](../research/cases/2026-10-30-real-evidence-studies.md)

第三版最初重构见[计划](phase-3/2026-10-29-clean-rebuild-plan.md)、[实施](doing/2026-10-29-clean-rebuild-implementation.md)。

过期二期计划与执行台账已移至 [研究归档](../archive/research/20261030-consolidation/README.md)，代码与同期设计另有 [r11完整归档](../archive/phase-2/20261029-clean-rebuild/)。历史“当前状态”不可覆盖今天事实。

2026-10-31重新核验官方[接入指南](https://agentmemoryleaderboard.ai/api-guide)：模型限制、同步Add、30分钟期限、user_id范围、Top K与调用方重试均已对照本版。运行与提交事项见部署说明；尚未实际部署或通过官方smoke。
