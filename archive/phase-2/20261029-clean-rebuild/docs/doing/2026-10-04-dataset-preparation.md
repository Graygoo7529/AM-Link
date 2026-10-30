# 数据集目录与转换计划

> `superseded`：本文为初版历史设计，其中 dataset 生成 Add/Search manifest、runs 放 dataset 下的方案已被 [2026-10-05 解耦方案](./2026-10-05-dataset-decoupling.md)取代。当前命令见 [dataset](../../dataset/README.md)。

日期：2026-10-04；状态：`in_progress`。

## 范围和目录设计

- `dataset/catalog.json` 分成 `datasets`（已有支持读取器，可由当前 fetch/prepare 命令处理）与 `public_sources`（上游公开来源、许可和处理方案已核实，但尚未下载或接入）。避免把 metadata-only 数据错误地当成可运行样本。
- `dataset/data/raw/` 保存明确选择获取的源文件；`derived/` 保存带来源 hash 和切片条件的 manifest；`runs/` 保存含实际请求/响应的 report 和 trace。上述均为 Git 忽略路径。
- Add manifest 只包含历史输入。问题、答案、preference、rubric 和 source evidence 标注仅用于 Search/evaluator/诊断，不得泄漏到 Add。
- `dataset/prepare.py` 只做结构化读取、切片、source evidence 映射和官方 Add/Search 字段映射，不做 Answer、模型推理或官方评分。

## 已实施

- 清单详列 LoCoMo 原始版、LongMemEval-S 作者清理版；调研 catalog 登记 LoCoMo-Refined community candidate（固定 commit `887091190789e8d6760e70b9edd696539923dc4f`）、LongMemEval-M/Oracle、ScriptMem、CL-bench/Life、PersonaMem-v2、BEAM/10M。
- LoCoMo 原始公开文件已存在于 `dataset/data/raw/locomo/locomo10.json`：2,805,274 bytes，SHA-256 `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`，10 conversations、272 sessions、5,882 turns、1,986 QA。许可 CC BY-NC 4.0。
- `dataset/fetch.py` 只从可运行 `datasets` 选择单一数据源，按 pinned URL 下载、核 SHA（有已知值时），先写 `.partial` 后原子替换。不会批量抓取 metadata-only public_sources。
- `dataset/prepare.py` 支持 LoCoMo 和 LongMemEval-S。可按 conversation/question ID、类别/题型、session、question 数、Add 消息 chunk 数、Search `top_k` 控制。
- 新 manifest 中每条 LoCoMo evidence target 带 dataset record、`dia_id`、session 和源 Add request ID；LongMemEval 带 question record、session、turn index、Add request ID，便于靶场逐样本追溯。
- LongMemEval-S author cleaned 文件约 277 MiB，revision `98d7416`。本轮下载返回 HTTP 502；fetcher 已清理 `.partial`，状态仍为 `not_downloaded`，成功取得后应算本地 SHA 并核 schema。
- LoCoMo-Refined community raw JSON 已固定完整 Git commit 并登记 pinned URL；本轮 GitHub raw 请求也返回 HTTP 502，没有生成文件，SHA/schema 保持待核验。

## 转换和评分方式

- LoCoMo：每个 conversation 是独立 user；原始 session/turn 顺序入 Add；`evidence` 中 turn id 必须能映射至所选 history 才保留题目。按 source turn 原文计算 literal evidence recall/rank/chain coverage。
- LongMemEval-S/M/Oracle：每题是独立 user，S/M session 以原时间戳顺序入 Add，`has_answer` turn 映射检索 target；Oracle 只有 gold evidence sessions，单独作为容易数据流检查。author `evaluate_qa.py` 使用 Answer hypothesis + judge 的 QA 分，属于靶场外的可选 Answer/Eval 阶段。
- CLBench/Life：OpenAI `messages` 中分 context 与 task，history 才进入 Add；`rubrics` 留 evaluator。没有源 span 时不能报告 evidence retrieval recall。
- PersonaMem-v2：冻结 HF split/persona，取得并许可检查引用 history；history 入 Add、`user_query` 用于 Search，preference/正确答案只供 evaluator。
- BEAM：先单行、单个 128K 对话，流式读取 chat 并按消息上限分 Add；probing questions 与答案留给 evaluator。10M 单列压力计划。
- ScriptMem：只用公开题型/answer evaluator 做 QA 材料研究；不将缺失的原始影视剧本或 synthetic example 当成历史输入。

## 已运行核对

- 固定 LoCoMo `conv-26`、前 4 session、category 1/2/3 每类最多 2 题：5 Add / 6 Search，8/8 source evidence 的 Add request 映射均可解析。当前 builder v2 manifest SHA-256 `efabcb565df8ac7de46482d9306cd158eed063bc49c8ea5f24977e76fce2389c`。
- LoCoMo 检查：10 conversations、272 sessions、5,882 turns、1,986 QA；category 1–5 题数分别为 282、321、96、841、446。
- source reference 更新后的 4 项 `dataset/tests` 通过。
- 上游非 LoCoMo 文件尚未写入工作区；不把网页可见的行数当本机取得状态。

## 待办

- [x] 登记相关作者/维护方数据源、许可、格式、split/use/evaluator 及未下载状态。
- [x] 现有 converter 追踪 evidence source 到 Add request，保持 gold 不入 Add。
- [x] 留存可复现的 LoCoMo 本地 smoke 文件与摘要。
- [ ] 网络可用时下载 pinned LongMemEval-S；对一个小切片检查实际字段和来源映射。
- [ ] 视近期验证与许可确认，将 community LoCoMo-Refined 作为独立 dataset source 接入，不与 AML bundle 混名。
- [ ] 每接入一个新数据源，先补 schema/label leakage 测试和手工抽样，再启用打分。

## 文件索引

- [`README.md`](../../dataset/README.md)：获取、使用和评分边界。
- [`catalog.json`](../../dataset/catalog.json)：机器可读源 catalog。
- [`prepare.py`](../../dataset/prepare.py)：读取、切片和 manifest builder。
- [总调研](./2026-10-04-dataset-research.md)：公开源详细交叉核验。
