# 项目记忆

## 当前状态（2026-10-30）

AM-Link 是 Graygoo7529 参加 Agent Memory Leaderboard 的原创记忆系统；只提供 Add/Search，官方负责 Answer/Eval。TinySoul-Agent 同为作者原创参考项目。

当前 `amlink/` 为第三版 `0.3.0-clean`、DB300：不可变原文与精确episode双索引；跨Add小批缓冲；Reflection单次生成来源校验的短导航note；Search词法/向量融合、原文来源反链及有界邻接、最多两轮Select与具体补查。没有自由BFS或语义图边，不恢复二期复杂草案审查。模型固定 `text-embedding-v4`/1024 与 `gpt-4o-mini`，默认真实使用；不做内部错误重试。

第三版100题真实测试已完成：方法冻结4191890，六类26份完整准备历史、780/780 Add、100/100 Search、100/100 Answer；Reflection726/732完成（3工具结构、2来源列表、1笔记超限失败）。3607尝试/3607响应，输入5774218、输出223977tokens。mini初评54正确/41未达标/5评分失败；Codex审读全部回答为51正确/47未达标/2不确定，其中22题另读实际证据。公开研究集、无官方成绩/泛化保证。整理完成率不是语义正确率。默认数据库仍空；尚未部署。

用户提交0d944b6后确认整合 `benchmark`、`casestudies`、`visualization` 为 `research/`，`dataset/` 保持独立。本轮实施研究整合，生产方法仅改native研究导入、不改Add/Search算法、不新增真实模型调用。36案例中16建立深入实测链路，100题保存回答复核；未深研题明确标记。

## 每次先读

1. 根 `README.md`、`docs/README.md`、`DESIGN.md`。
2. `docs/phase-2/integration-research.md`（比赛背景；上次在线核验不是今日重新核验）。
3. `research/README.md`、`docs/phase-3/2026-10-30-evidence-method-review.md`、`docs/doing/2026-10-30-research-consolidation-implementation.md`。
4. 实测详见 `docs/doing/2026-10-30-hundred-answer-report.md`、同前缀ledger及 `docs/phase-3/2026-10-30-hundred-answer-execution.md`。按任务需要再读历史长文。

## 唯一研究入口与数据

- `research/benchmark/`：请求适配、执行、Answer/Eval、观测、运行登记与评注。
- `research/cases/catalog.json`：唯一案例身份和理论/实测登记；具体文档在同目录。
- `research/web/`：页面构建，命令 `python -m research.web.build`。
- `research/data/index.html`：唯一生成页面；按运行加载 `runs/*.js`，普通浏览器可离线打开。无独立案例页/百题页；页面选择状态不保存。
- `research/benchmark/data/runs/hundred30-*`、`research/benchmark/data/plans/clean30-hundred-answer/`：原始100题证据与冻结计划。不要改写历史快照里的路径/哈希，不把重放或新代码结果混入旧分母。
- 原文、模型完整I/O、库、生成页面都在忽略data路径。来源标注/gold仅评估侧可见，不能泄入Add/Search。评注按运行/数据/轨迹/步骤绑定，追加保存。

## 核心边界

成功Add表示有效原文、episode、BM25/向量和必要遗忘已原子提交；整理可待处理或不完备。提交前必要操作失败则不留半轮写入；相同request_id同内容重放不重复模型调用，换内容拒绝。Search独立只读已提交记忆，不消费WorkingMemory，不触发Reflection，不执行Answer。模型配置和源码只保留当下真实可用的路径，不引入默认关闭的研究功能或失败时隐藏降级。

未解决的明确问题：遗忘后的助手确认回流；候选被近似主题/邻接挤占；原文片段缺事件标题或语气/时间归属；Select不知道交付预算；外部Answer误读已有证据及mini评分偏差。下一轮方案在method-review，尚未实施，不宣称有新质量收益。先验证这些直接断点，再讨论恢复图。

## 历史保留

一期0.3.0归档在 `archive/phase-1/`，一期已完成比赛并清理部署；二期r11（26/75 Reflection）源码/设计在 `archive/phase-2/20261029-clean-rebuild/`。旧研究页面、19份较早实验、旧计划、过期执行文档及本文件之前的完整项目记忆在 `archive/research/20261030-consolidation/`；没有永久删除。旧资料的“当前/待实施”不是今天状态。新实验使用新库，不恢复旧库起步。

本轮未改私有配置/依赖、未部署、未自动提交。此前真实原文浏览器访问被自动审批拒绝；不得换通道绕过。可在文件工具分析真实数据，UI验证只使用无真实数据的合成fixture。明确区分实际浏览器验证与静态/数据校验。
