# 数据集目录

这里保存数据来源与数据处理规则；完整原文、派生 manifest 和运行记录放在 `dataset/data/`（Git 忽略）。本目录只记录公开上游数据。AML 受限/隐藏测试集不会复制到此处。

## 当前可运行的数据

| 数据集 | 状态 | 格式与许可 | 用途 |
| --- | --- | --- | --- |
| LoCoMo 原始版 | `available`：从归档中的本地公开副本复制，保留字节与 SHA-256 | JSON，CC BY-NC 4.0；10 conversations、272 sessions、5,882 turns、1,986 QA | 当前默认 smoke/dev 切片；按原始 turn evidence 测检索召回 |
| LongMemEval-S 清理版 | `not_downloaded`：上游约 277 MB，本机 HTTPS 握手失败 | JSON，作者 Hugging Face 数据卡标注 MIT；500 questions，每问通常约 40-50 histories / 115K tokens | `prepare.py` 可按 question 做小切片；gold 以 turn `has_answer` 标记建检索任务 |

原始 LoCoMo 文件 SHA-256：`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`。该值可用于核对归档副本、`dataset/data/raw/locomo/locomo10.json` 和公开源下载内容。

比赛官方 Refined bundle 与公开源文件不是一回事。目录中不存放官方隐藏题、金标、私有标注或从官方结果重建的数据。其余数据集、许可、规模及限制见[官方数据集调研](../docs/doing/2026-10-04-dataset-research.md)与机器可读[数据集清单](./catalog.json)。

## 获取原始数据

只下载明确指定的公开数据，不会批量获取全部大文件：

```powershell
.\.venv\Scripts\python.exe dataset\fetch.py locomo
.\.venv\Scripts\python.exe dataset\fetch.py longmemeval-s
```

LoCoMo 已在本机：`dataset/data/raw/locomo/locomo10.json`。如果文件存在，fetch 会核对 SHA-256 并保持原文件。LongMemEval-S 下载约 277 MB，会使用清单中钉住的上游文件 revision，并报告本地摘要。网络受限时可从浏览器取得同一公开文件，再放到 `dataset/data/raw/longmemeval/longmemeval_s_cleaned.json`；转换 manifest 时同样读取本机原始文件。

## 检查与切分

查看已取得文件：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py inspect --dataset locomo
.\.venv\Scripts\python.exe dataset\prepare.py inspect --dataset longmemeval-s
```

生成一个固定的小型 LoCoMo Add/Search manifest（`conv-26`、前 4 个 session、类别 1/2/3 各最多 2 题）：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset locomo --conversation-ids conv-26 --session-limit 4 --category 1 --category 2 --category 3 --questions-per-category 2 --output dataset\data\derived\locomo-smoke.json
```

指定稳定的 conversation ID 以固定切片；显式扩规模而不要把部分运行称为完整基准：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset locomo --conversation-ids conv-26,conv-30 --session-limit 4 --questions-per-category 3 --output dataset\data\derived\locomo-dev.json
```

LongMemEval-S 先固定题目 ID/题型/上限；每个问题是一个独立 user scope，其输入包含该问题的完整 haystack session，可用 `--session-limit` 评估较小的历史切片：

```powershell
.\.venv\Scripts\python.exe dataset\prepare.py build --dataset longmemeval-s --question-limit 1 --session-limit 8 --output dataset\data\derived\longmemeval-smoke.json
```

这类截短问题不能直接与原 benchmark 全量结果比较。含 gold turn 的 question 用原始 turn 作为 `contains_any` target；只有数据源明示的 `has_answer` 会成为目标。答案正文不会被加入 Add 请求。Abstention 要依赖下游回答模型，本靶场当前不把“无目标证据”误判为“Search 必须返回空数组”。

## 数据处理契约

`prepare.py` 会输出带上游 URI、输入 SHA-256、许可、选择规则與构建工具版本的 JSON manifest。LoCoMo 保持对话/session 顺序，每 20 条消息分块 Add，保存原始角色/文本、时间戳和可得的图像描述；只有能映射到保留原始 turn 的 QA evidence 才参与检索评分。LongMemEval-S 按时间顺序写入每问 history，每 20 条消息分块，并保留 `has_answer` turn 来源作为检索目标。

Builder 只构造 Add/Search 输入、题目与证据目标；它不实现回答、不将 `answer` 文本当成记忆，也不调用模型。完整运行通过 [`benchmark/`](../benchmark/README.md) 中的服务 API adapter 完成。

## 许可与留存

- LoCoMo：遵循上游 CC BY-NC 4.0，注明原作者 SNAP Research 与论文，不做商业用途。公开仓库没有作者原始图片，只能用 JSON 内可得的 BLIP caption。
- LongMemEval-S：清理版 Hugging Face 卡标 MIT；仍标明 Di Wu 等作者与原仓库/Hugging Face 来源。
- 其他数据集：下载前单独核验原始语料授权；代码仓库的 LICENSE 不能自动适用于数据。
- Benchmark run 的 manifest、完整 Add/Search trace 和 target evidence 可还原样本内容，存储在 Git 忽略区；仅为本地个人分析读写，不上传或提交。
- 如果以后获得 AML 专用评测数据，则不放入这个公开数据目录。对该副本及派生数据遵守官方用途限制和 run 后保留期限。
