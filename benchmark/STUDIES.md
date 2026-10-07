# 案例实验与研究工作区

2026-10-07，done。入口是 `python -m benchmark study`。将“来源选择 → 真实 Add/Search → 内部观测 → 评注 → 本地网页”串为一次可复核实验。正式比赛仍由主办方执行 Answer/Eval；这里不增加 AM-Link Answer API。

## 选择数据与运行

仓库根目录，先从无需模型的本地基线开始：

```powershell
# 完整范围：该案例所属记录在基础 pack 中的全部历史
.\.venv\Scripts\python.exe -m benchmark study --case lm4 --scope full --target lexical

# 最小诊断：仅案例目录明确指定的原文锚点
.\.venv\Scripts\python.exe -m benchmark study --case lm4 --scope anchors --target lexical

# 加回每个锚点前后各两条发言；不跨会话拼接邻居
.\.venv\Scripts\python.exe -m benchmark study --case lm4 --scope window --radius 2 --target lexical

# 指定任意已准备的数据包、记录、问题；不需要先编写案例文章
.\.venv\Scripts\python.exe -m benchmark study --dataset-pack dataset/data/prepared/locomo-full.json --record conv-26 --task qa-11 --plan-only
```

`--record` 可重复选多条记录；`--task` 与 `--turn` 的选择要求单条记录，避免同名 ID 跨记录歧义。`--turn` 与 `--scope anchors|window` 搭配。`--top-k`、`--chunk-size` 固定本次返回预算和批次。`--before <毫秒时间戳>` 使用严格小于界限；遇到无日期的片段拒绝猜测。多个过滤条件取交集。

原始数据先通过 `dataset.prepare` 或特定来源读取器成为中立 pack，见 [数据层](../dataset/README.md)。此命令不自动下载、不把任务标注转成历史、不将 S 换成 Oracle。`full` 只表示所选基础记录完整，不能称为整个来源的全量评测。

案例的 `data` 绑定唯一保存在 `casestudies/catalog.json`。`turns` 是研究者选的诊断锚点，可能包含反例或冲突旧值，**不等同于作者证据标注**。空锚点的案例可跑 full，不能臆造 anchors。

切片若移除了作者标记的证据，默认失败；显式 `--allow-partial` 后保留原标注，但相关检索题设为不评分。`selection.json` 记录基础包指纹、原始选择、所选 ID、时间界限、片段数、遗漏证据和人工辅助选择标记。无证据标注的题同样不评分，绝不自动要求检索为空。

## 保存与重新加载

实际运行生成独立的 `benchmark/data/runs/<run-id>/`，已有目录拒绝覆盖。包含 pack 快照、plan、selection、trace、report、观测事件与产物。默认登记到 `benchmark/data/research/workspace.json`，自动重建 `visualization/data/local/index.html`；`--no-view` 可延后页面构建，`--plan-only` 只生成忽略目录中的计划。

页面重建不调用目标或模型。默认装入最近五个登记运行；超过会话展示容量会减少较早运行，并在“持久运行档案”显示全部 ID 与载入范围。原始运行和评注不会删除。可以只加载指定运行，支持重复参数：

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --workspace --workspace-run lm4-full-20261007 --workspace-run lm4-anchors-20261007 --web
```

每个运行页面最多展示 20 道查询，界面标出展示/实际数量。更大实验应按研究问题拆成独立运行；全部 trace 仍在运行目录。单次运行大到超出展示上限时构建会明确报错，运行结果已保存，可改用更小实验或检查原始轨迹。

既有 Mem0 Answer/Eval 补充记录可以登记并在以后自动加载：

```powershell
.\.venv\Scripts\python.exe -m benchmark workspace register --run benchmark/data/runs/mem0-microstudy-20261007 --observations benchmark/data/runs/mem0-microstudy-20261007/observations-reviewed.json
.\.venv\Scripts\python.exe -m benchmark workspace publish
```

## 方法接入与埋点

- `lexical`：本地内存原文存储，按 user 隔离和 request 幂等；英文词项 BM25，正文打分，没有改写、摘要、向量模型、重排或 Answer。语料、候选、分数、返回选择和写入产物均有实测事件。中文材料可加载，但当前分词不适合中文召回，不能当作中文能力结论。
- `aml-api`：复用现有 HTTP 对象适配器，配合 `--base-url` 和认证环境变量。只自动采集 API 边界，服务内部要自行接入 [观测接口](./OBSERVABILITY.md)；网络失败和正常空结果分开。
- `native`：`--factory <可导入模块>:<工厂>` 创建本地方法，工厂只收到 `recorder` 和 `artifacts`，返回提供 `add(request)` / `search(request)` 的对象，响应类型为 `TargetResponse`。方法不会收到 pack、答案、gold evidence 或评分计划。需设置 `--system-name` / `--system-version`，工厂实现位置属于二期新目录，不能改写一期归档。

本地方法实现 `set_observation_parent(parent)` 接收当前 Add/Search 根 span。执行真实操作时：

```python
# 在方法自己的 add/search 内；parent 来自 set_observation_parent
with recorder.span("store", name="保存本次有效事实", parent=parent,
        record_id=parent["record_id"], task_id=parent["task_id"],
        request_id=parent["request_id"]) as step:
    # text 必须来自实际保存结果，不能把理论模板当结果写进来
    ref = artifacts.text("memory", actual_saved_text, title="本次保存后的事实")
    step["outputs"] = [ref]
```

`artifacts.text` 写入可显示的 `amlink.artifact.v1` 正文：schema_version/title/text。可视化只投影这个明确声明的格式，并核验文件路径、大小和 SHA。普通 `artifacts.write(kind, value)` 可保存更完整的本地结构，但 native 未声明的结构不会自动展开到页面。每条引用的文件上限为 5 MB，超大记录需要拆分。不要放凭据或鉴权头。

方法应在模型实际调用处记录 model span，使用 tokens/费用未知时保留 null。只有真正完整捕获调用的 native 方法才设置 `model_capture_complete = True`；默认未知，不能从 HTTP 成功推断增强成功。此次本地基线完整声明为零模型调用。每个实际内部阶段用标准 operation；未使用的模块不能编造事件，未采集的步骤也不能填成“已成功”。

如需本地 Answer/Eval，继续使用独立 observations/标准 answer、eval span 接入；回答模型只看到 Search 实际交出的上下文，评分器才读取 gold。当前 study runner 不自动执行通用 Answer，已有 Mem0 六条件结果展示这条下游接入路径。

## 持久评注

页面可按查询或具体 span 填写“观察事实 / 待验证假设 / 下一步实验”，生成带身份与哈希的 JSON 草稿。静态网页不能静默写回工作区；复制保存后按页面给出的命令导入，也可以让助手直接记录：

```powershell
.\.venv\Scripts\python.exe -m benchmark workspace note --run benchmark/data/runs/lm4-full-20261007 --search gpt4_d84a3211:question --stage search --kind hypothesis --author "研究者" --text "需要测试事件维度的查询分解。"
# 页面生成的草稿：
.\.venv\Scripts\python.exe -m benchmark workspace import-note --run benchmark/data/runs/lm4-full-20261007 --file <评注文件.json>
```

评注存入该运行的 `notes.jsonl` 并更新网页。绑定 run/pack/trace/search；可选 `--span` 还必须匹配查询和阶段。错误运行、错误哈希、重复导入均拒绝。更正用 `--supersedes <旧评注 ID>` 追加新记录，旧评注仍可追溯。页面不保存选择状态；未导入草稿不是持久评注。

## 评价边界

字面标记覆盖、完整证据链、回答正确率分开报告。新报告只有请求预算达到 k 的题才计入 @k，分母用 `eligible_queries@k` 表示；top-5 运行不再伪报 @10。早期报告保持原貌，不能直接与新口径混合。没有回答就没有问答准确率；缺少内部观测不能推断失败模块。

案例实验用于形成与证伪机制假设。来自失败分析的例子已被研究者选择，不是独立测试集。方法调好后必须按人物/历史组隔离，另选未参与设计的记录验证。
