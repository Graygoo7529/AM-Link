# 研究可视化体系 v1

状态：五视角、16 个案例、真实 pack 摘录、全量结构统计、本地 BM25 对照与 benchmark 轨迹接入；记忆系统对比试验与自动归因仍为后续工作。

## 共同身份与证据边界

`dataset_id → record_id → task_id → turn_id/字符范围 → run_id → search_id/result_rank` 是连接路径；展示案例 ID 只作索引，不能替代数据身份。每个本地导入记录原文件 SHA-256，run 使用运行时 pack 快照，不能用后来更新的 pack 替换。

标注四种证据类型：

- `source`：实际文件中的历史、任务及标注；真值标签可能有误，引用存在不保证答案正确。
- `theory`：人工分析的合理 Add/Search/Answer 路径；不是目标内部执行记录。
- `observed`：trace 中实际请求、返回内容、耗时和显式步骤记录；仅代表可见边界。
- `missing`：未采集/未运行/无评分依据；不能渲染成 0 分或成功。

Answer 是下游回答阶段，正式比赛仍由主办方负责。可视化呈现结果不等于 AM-Link 要提供 Answer API。所谓“推理路径”限于可核验的证据依赖与公开执行步骤，不臆造模型隐藏思维链。

## 原始材料到评分的分流

history 保存原文、人物、时间及来源；task 保存当前输入；annotations 保存标准答案、evidence、rubric、偏好标签等。作者附带的背景生成计划、观察与摘要另标注，不默认用于 Add。不同来源字段可能同名但含义不同，依照具体读取器解释。

数据概览区分全量来源、小样本、派生 pack 与展示摘录。LoCoMo 的 turn、PerLTQA 的来源文档、CL-bench 的消息不能混成同一分母。共享历史的原版与 Refined 不是独立数据集切分。

`research.json` 保存原始文件 census 的聚合投影、源文件与本地产物哈希、BM25 的分母及证据覆盖；原文、逐题排名和模型日志留在忽略的 `data/`。`visualization.research` 校验 census 与对照使用同一 LongMemEval 源文件。新增统计先更新生成器再重建，不能只手改页面数字。

PersonaMem-v3 历史按 persona 和 `timestamp < query timestamp` 切片。顶层字段使用可观测字段白名单；嵌套 `conversation_json` 只保留 role/content，同时保留独立 user_message。偏好演化、未来反馈、生成索引和 gold 均不进入 Add。

## 运行接入契约

当前读取 `benchmark/data/runs/<run-id>/{dataset-pack.json,plan.json,trace.jsonl,report.json}`。校验报告与计划的 pack digest、数据源 ID、run ID 以及 Search 对应的 record/task。`manifest_sha256` 在现有 runner 中是限量前计划 digest，不能用限量后的 plan.json 文件哈希直接比较。

展示当前问题之前已发生的 Add，按完整 namespaced request ID 连接来源，避免凭相同字符串跨用户合并。原文匹配是靶场的字面诊断，不能等同于语义证据支持或答案正确。模型调用次数、费用和 Answer 没有记录时保持未知。

跨来源受控实验可在 record.attributes 中声明 `dataset_key / case_id / variant`；导入器只投影这三个字段到 query.research_case，连接原案例并显示“短片段实验”。它不能把短片段实验冒充完整历史测评，也不能让理论路径成为观测步骤。

真实样本与轨迹只进入本地忽略目录；展示原文有长度上限且标注省略，不修改底层文件。独立网页不对外发布，也不连接目标服务。

## 后续 Answer/Eval 与步骤导入

结构化内部事件使用 [`benchmark/OBSERVABILITY.md`](../benchmark/OBSERVABILITY.md) 的版本化接口，独立于展示层。每条原文/记忆/候选/上下文都通过 artifact 哈希与 locator 对齐；父子 span 表达实际调用关系，来源 links 表达证据关系。下述 observations 是补充正文投影，不替代内部事件契约。

可选 `--observations` 接受人工核对后导出的 JSON，不会自动运行 Answer。示例是格式说明，不是实验结果：

```json
{
  "schema_version": 1,
  "observations": [{
    "run_id": "existing-run-id",
    "record_id": "existing-record-id",
    "task_id": "existing-task-id",
    "dataset_pack_sha256": "same-canonical-digest-as-run",
    "answer": {
      "text": "实际生成的回答",
      "model": "实际模型版本",
      "prompt_version": "固定提示词版本",
      "context_result_ranks": [1, 3],
      "source_artifact": "本地回答日志及事件定位"
    },
    "evaluation": {
      "label": "实际判定",
      "metric": "准确指标定义或 rubric 版本",
      "evaluator": "实际评估者/模型版本",
      "source_artifact": "本地评分日志及事件定位"
    },
    "steps": [{
      "stage": "search",
      "description": "目标显式记录的查询改写/工具步骤",
      "source_artifact": "目标公开 trace 的事件定位"
    }]
  }]
}
```

关联对象必须存在；缺少身份、来源或 Answer 的评估记录报错，不能静默丢弃。这里只验证结构与关联，不认证模型/评估者的真实性；界面注明“导入的观测记录”。不得将人工推测填写成 steps。精确 Answer 上下文裁剪需要未来记录每条结果的可见字符范围，当前 ranks 只能表示来源结果集合。

## 迭代顺序

1. done：五视角共用来源与案例标识；网页/会话同源；真实历史摘录与现有 API 轨迹可视化。
2. partial：Mem0 六条件已接入实际 Answer、定性审查、模型 span 与写入快照；完整历史、多方法公平对照及官方评分器尚未完成。
3. todo：同 pack、同任务、同预算的多方法并排比较；缺失项不混入分母，固定评估器与费用口径。
4. todo：增量检查点、更新/遗忘轨迹、证据到最终上下文的裁剪可视化。
5. partial：已展示全量问题类型分布、本地 BM25 链覆盖和 Mem0 短例延迟/调用；费用未知，多方法并排比较待做。小样本与完整集分开报告。

通过新增 profile、case 或 run 扩展内容；只有新视角才扩展界面。不要把每次分析做成互不相连的新页面。
