# 公开数据集目录与转换计划

日期：2026-10-04；状态：`in_progress`

## 范围与设计

- 只整理公开上游语料，登记来源、版本、许可、原始格式、体量和 AML 公开套件的对应关系。
- `dataset/data/raw/` 保存原始文件，`dataset/data/derived/` 保存固定规则生成的 manifest；两处均被 Git 忽略。只按需获取单个数据集。
- manifest 使用比赛 Textual Add/Search 输入形状，并增加 evidence target、类别及完整来源/hash/slice 元数据。答案不写入 Add；证据未包含在所选 history 的题目不参与该切片。
- 原始公开上游和 AML `Refined`/冻结 bundle 分开标注。数据整理器只做切片和字段映射，不做 Answer、模型推理或官方评分。

## 已实施

- `dataset/catalog.json` 当前登记 LoCoMo 原始版和 LongMemEval-S 清理版，包括源 URI、LoCoMo SHA、LongMemEval-S 固定 HF revision 和本地状态。
- `dataset/fetch.py` 按清单单个下载、校验 SHA（清单有值时）、先写 `.partial` 再替换目标文件；没有配置批量下载。
- `dataset/prepare.py` 支持 LoCoMo/LongMemEval-S 检查和 manifest 转换；JSON 数组使用标准库增量读取，支持 question/category/conversation/session/chunk/top-k 限制。
- LoCoMo 已从一期被忽略的本地公开副本复制到 `dataset/data/raw/locomo/locomo10.json`，逐字节相同；不触碰归档文件。
- LongMemEval-S 暂不下载：上游 HTTPS 在当前环境握手失败。其大文件无预先核实的 SHA，成功获取后必须记录本地摘要；session 截片仅保留 gold evidence session 完整包含的题目。

## 验证

- LoCoMo 输入 SHA-256：`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`。
- 固定 smoke manifest SHA-256：`ce621c6f65063ecc7f32cd6ee14752f29d29e55a3862d61bfd22cb9d4d07ce4a`；重复构建值相同。
- `inspect --dataset locomo`：10 conversations、272 sessions、5,882 turns、1,986 QA；category 1–5 计数分别为 282、321、96、841、446。
- 固定 `conv-26`、前 4 个 session、category 1/2/3 各最多 2 个问题，可生成 5 Add/6 Search。两次独立生成得到相同输入和摘要；生成物留在 ignored `dataset/data/derived/`。
- `python -m unittest discover -s dataset\\tests -v`：4 项通过，覆盖分块 JSON 读取、LoCoMo 证据/答案边界、LongMemEval `has_answer` 和截片后有效题目限量。

## 待办与判据

- [x] 许可与公开数据边界有可读清单和机器可读 catalog。
- [x] LoCoMo 原始数据、检查器与固定 smoke manifest 可复现。
- [x] LongMemEval-S converter 使用 answer-session/turn 标记，且 Add 不含 gold answer。
- [ ] HTTPS 可用时获取 LongMemEval-S pinned file，计算摘要并对上游实际 schema 进行小样本适配核验。
- [ ] 下载/使用其他数据前逐一确认数据许可和 reader；当前不下载 CLBench、PersonaMem、BEAM、ScriptMem 或多模态素材。

## 可比性限制

LoCoMo 公共原版不能代表 AML LoCoMo-Refined。LongMemEval 检索 evidence recall 不能代替 answer/judge accuracy；按 session 截短后的子集也不能与上游全量成绩比较。完整数据集比较范围和官方隐藏数据边界见[总调研](./2026-10-04-dataset-research.md)。
