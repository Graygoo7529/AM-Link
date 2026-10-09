# AM-Link 可观测性标准接口 v1

状态：接口约定、Python recorder、校验器与研究视图接入已实现；Mem0 研究实验和 AM-Link 二期 0.1.0 均已接入 native 内部步骤观测，并保留真实模型切片档案。AM-Link 尚未部署或参加官方 Smoke。此接口是诊断侧接口，不改变比赛 Add/Search API。

靶场的 `ObservedTarget` 自动提供 API 根 span；native 工厂可通过 `set_observation_parent` 连接内部步骤。`Artifacts.text` 提供 `amlink.artifact.v1` 可显示正文，`amlink.note.v1` 将研究评注绑定到真实查询/步骤/哈希，详见 [接入与评注指南](./STUDIES.md)。两者是独立附属格式，不修改 observation v1 事件字段。

## 覆盖范围

| operation | 需要记录的可见事实 |
| --- | --- |
| add | 实际输入来源、逻辑 request_id、尝试次数、成功/错误、幂等命中或恢复 |
| extract | 原文来源 → 派生记忆的关联；实体/时间等产物由带哈希的 artifact 定位 |
| store / index | 成功写入的版本或快照引用；成功并不自动代表所有增强完成 |
| search | 原始 query 引用、最终返回结果及顺序、错误与耗时 |
| retrieve | 查询改写/扩展后的 query 引用、候选及检索分数、候选来源 |
| rerank | 排序前后候选、实际 rank/score、是否选中；不同方法分数不可直接横比 |
| context | 最终可见上下文 artifact，引用精确片段；被裁剪/排除的候选 selected=false |
| answer | 实际上下文 → 回答 artifact；模型版本记录在子 model span |
| eval | 回答 → 评估 artifact；指标/rubric、评估器版本和判定保存在 artifact |
| model | 每一次真实模型调用一个 span；token/费用若未提供则 null，失败尝试也记录 |

内部可见步骤是公开事件和产物来源关系，不收集或伪造模型隐藏思维链。原文、记忆、答案和评分文件留在本地 `data/`，事件只保存引用；不记录 Key、Authorization、连接密码或整段异常消息。

## JSONL 事件约定

每行是一个完成的 span，`schema_version=amlink.observation.v1`。精确字段和验证入口见 [`observability.py`](./observability.py) 的 `validate_event`。事件分为：

- 身份：run_id、dataset_pack_sha256、trace_id、span_id、parent_span_id、record_id、task_id、request_id。
- 阶段：operation、name、attempt（从 1 起）、replay（none/cached/resumed）。同逻辑请求重试 request_id 不变；每次尝试的 span_id 不同。
- 时间与结果：带时区 started_at/ended_at、单调时钟 duration_ms、status（ok/error/skipped）、error（code/retryable）。空结果是成功 Search 且 outputs/candidates 为空；依赖失败必须 error。
- 证据：inputs/outputs 引用；links 为 derived_from/retrieved_from/selected_from/supports/contradicts/supersedes；只能连接本 span 已声明的引用。
- 候选：candidates 的 ref_id、rank、score（可 null）、selected；rank 从 1 起，不重复。
- 模型：model 为 null，或仅在 model span 中提供 provider/name/input_tokens/output_tokens/cached_tokens/cost_usd/usage_source；不可在父子 span 重复记账。

每个引用包含 `id/kind/artifact/sha256/locator`：artifact 是相对于运行目录的 POSIX 路径，sha256 为文件字节哈希，locator 定位 JSON pointer、turn 或字符范围。kind 为 source/memory/query/result/context/answer/evaluation。引用 id 应在运行中稳定且唯一代表同一产物；若要在同一 span 原样透传，只在 inputs 声明一次并在 candidates 引用。

source artifact 应保留源 dataset/record/turn 与字符范围；派生 memory artifact 应保留版本、实体、时间解释和原文来源。Web 不自动读取这些路径，只展示来源引用，防止导出时意外混入任意文件。分析者可在本机按路径和哈希另行核对。

## Python 接口

```python
from pathlib import Path
from benchmark.observability import ObservationRecorder

with ObservationRecorder(
    Path("benchmark/data/runs/<run>/observability.jsonl"),
    run_id=run_id, dataset_pack_sha256=pack_digest,
) as recorder:
    with recorder.span("search", name="memory.search", record_id=record_id,
                       task_id=task_id, request_id=request_id) as search:
        with recorder.span("retrieve", name="hybrid.retrieve", parent=search,
                           record_id=record_id, task_id=task_id,
                           request_id=request_id) as retrieve:
            # 实际执行检索后，将真实 inputs / outputs / candidates 填入 retrieve。
            pass
```

Recorder 创建新文件，不覆盖旧实验；异常默认记录类型和 retryable=false，调用者可提前设置更准确的错误分类。它不会自动重试，也不替业务决定成功。成功幂等重放用 replay=cached，不能再创建未实际发生的 model span。

写入错误会显式抛出；若业务决定不让观测故障中断服务，必须另报 `observability_incomplete` 并将该次诊断标为不完整，不能伪装有完整轨迹。完成式日志遇到进程崩溃可能缺父 span；导入器报告孤立子 span，不能当作根流程成功。未来可扩展 start/end 双事件，但需升级版本。

## 与现有 benchmark 和 visualization 的连接

将文件放到同一个 run 目录后，`python -m visualization.build --local --run ... --run-kind experiment --web` 会自动读取。必须与该 run 的 pack digest、record/task 对齐；Search/Answer/Eval 根请求使用 benchmark 的 search_id，Add 使用实际 namespaced request_id。parent/child 必须处于同 trace、record、task、request，时间范围相容。完整图导入验证 span ID、引用一致性和父子关联；不会用墙钟顺序冒充并行执行因果。业务 user_id 应在本地运行配置中映射到 record_id；真实租户标识无需向展示层暴露。

没有孤立步骤只代表关联通过，不证明全部行为已采集。若采集方确认已拦截该次运行的所有模型调用，可另写 `observability.meta.json`，字段必须为 `schema_version="amlink.observation.v1"`、相同的 `run_id` 和 `dataset_pack_sha256`、`model_capture_complete=true`、非空 `producer` 版本。导入器还要求每次 API 请求都有关联的 Add/Search 根步骤；它不认证采集声明真实性。缺少声明、孤立步骤或未知费用时，不输出确定的全运行调用/费用总计。Recorder 不自动签发完整声明。

links 的方向固定为 `from_id` 指向 `to_id`：memory derived_from source，result retrieved_from memory，context selected_from result，evidence supports answer，new supersedes old；contradicts 表示尚未解决的冲突，不自动挑选较新值。候选 score 的算法、索引版本和过滤条件应存入被引用的产物，便于解释排序变化。产物存储及业务埋点由后续 AM-Link 实现负责。

页面按实际问题显示 Search 及其子步骤，并包含该问题之前的相关 Add 步骤。默认 API trace 与内部观测缺一方时明确标记缺失。Answer/Eval artifact 的正文不自动解释为结果；若希望并排显示回答与评价，使用 [`visualization/DESIGN.md`](../visualization/DESIGN.md) 中带来源的 observations 投影。

## 建议验收门槛

1. 原文片段可以追到 Add、派生记忆、返回结果、最终上下文；缺一段报告断链。
2. 未记录用量是未知，实际零模型调用需在完整 trace 下计数确认；token/费用仅汇总 model span。
3. 错误、无结果、跳过、缓存重放可区分；失败尝试不会从耗时/费用中消失。
4. 引用完整性和传输成功与回答正确性分别报告；抽取内部不可见时不得自动归因。
