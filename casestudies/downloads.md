# 手动补齐数据

核对日期：2026-10-07。链接是作者发布页或文件入口；页面可读不代表本机已完成下载。已取得内容以 `dataset/data/` 的 receipt、revision 和 SHA-256 为准。

## 已完整取得的范围

- LoCoMo：完整文本 JSON；原始图片未发布在该仓库，本机只有 caption 等文本。
- LoCoMo-Refined 社区版：当前固定版本的完整历史与问答；不等于 AML 私有冻结包。
- PerLTQA：完整中文 memory/QA。英文版未下载，本次不把“中文完整”写成整个双语项目完整。
- ScriptMem：公开的 457 题已齐；完整实验仍缺剧本，作者不随仓库发布，无法给出官方剧本直链。

## 本轮取得范围与剩余缺口

| 数据集 | 当前本机 | 下载入口与应取内容 | 建议顺序 |
| --- | --- | --- | --- |
| LongMemEval | S/M/Oracle 已完整取得 | [S，约 277 MB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_s_cleaned.json?download=true)；[Oracle，约 15.4 MB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_oracle.json?download=true)；[M，约 2.74 GB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_m_cleaned.json?download=true) | S/Oracle smoke 已构建；M 后续按题型切片 |
| CL-bench | 完整 1,899 条 / 90.1 MB | [CL-bench.jsonl](https://huggingface.co/datasets/tencent/CL-bench/resolve/66122c88771ac4f09f163415902828b933e78899/CL-bench.jsonl?download=true)；[文件页](https://huggingface.co/datasets/tencent/CL-bench/tree/main) | 已下载；现有小样本 pack 仍单独使用 |
| CL-bench Life | 完整 405 条 / 29.3 MB | [CL-bench Life.jsonl](https://huggingface.co/datasets/tencent/CL-bench-Life/resolve/cd2589f/CL-bench%20Life.jsonl?download=true)；[文件页](https://huggingface.co/datasets/tencent/CL-bench-Life/tree/main) | 已下载；现有小样本 pack 仍单独使用 |
| BEAM | 100K/500K/1M 共 90 条，约 105.6 MB | [全部三档文件](https://huggingface.co/datasets/Mohammadta/BEAM/tree/main/data) | 已下载并解码；尚未构建全量 pack |
| BEAM-10M | 两个分片，共约 343.8 MB | [两个 parquet 分片](https://huggingface.co/datasets/Mohammadta/BEAM-10M/tree/main/data) | 已下载并解码；压力测试时使用 |
| PersonaMem-v2 | 5,000 题、200 persona、400 份历史 | [benchmark.csv](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/e3a5916/benchmark/text/benchmark.csv?download=true)＋[32K 历史目录](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/tree/main/data/chat_history_32k)＋[128K 历史目录](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/tree/main/data/chat_history_128k) | persona 521 的 32K smoke 已构建 |
| MemoryAgentBench | 四类共 146 rows，约 76.6 MB | [四类 parquet](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/tree/main/data)；[entity2id.json](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/blob/main/entity2id.json) | 已下载并解码；尚未适配读取器 |
| PersonaMem-v3 | samples 三表：100 profiles、221,817 events、15,791 queries | [作者文件页](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3/tree/main)；[数据卡](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3) | backend 未下载；后续按 persona 选择 |

PersonaMem-v2 本轮覆盖完整文本 benchmark 及它引用的历史，未下载 train/val、多模态以及其余 persona 历史；这些属于其他研究范围。Persona 521 的 [32K 历史文件](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/e3a5916/data/chat_history_32k/chat_history_250913_163134_persona521.json?download=true)已在本机，不再需要手动补齐。

补充范围：PerLTQA [英文版](https://github.com/Elvin-Yiming-Du/PerLTQA/tree/8d9e19868e239740ef701e603ec205cd581f221b/Dataset/en)及 [en_v2](https://github.com/Elvin-Yiming-Du/PerLTQA/tree/8d9e19868e239740ef701e603ec205cd581f221b/Dataset/en_v2) 均未下载；如研究双语再取。ScriptMem [作者说明](https://github.com/memorax-ai/ScriptMem)解释了剧本缺口；LongMemEval-Refined 的 AML 冻结包也没有可核验的独立公开下载入口。

## 下载后放在哪里

统一放到 `dataset/data/manual/<数据集名称>/`，保持原文件名及目录结构；该目录已被 Git 忽略。同时保存来源 URL（例如写在同目录 `source.txt`）和下载日期。有多个版本时另建版本子目录，不覆盖当前 raw 文件。

后续让我读取这个目录即可：先辨别 JSON/JSONL/CSV/Parquet 的真实内容与完整性、记录版本/哈希/许可，再转换为当前 pack。本轮自动取得的文件位于 `dataset/data/raw/`，都有独立 receipt。现有通用读取器支持 JSON/JSONL/CSV；Parquet 本轮通过额外工具核验，但通用 pack reader 尚未接入。文件“已下载”、转换“成功”和记忆效果“已验证”分别记录。

本轮实际取得与核验结果见 [2026-10-07 重试记录](../docs/doing/2026-10-07-huggingface-retry.md)。完整第三方数据不进入 `casestudies/` 或 Git；可运行 pack 与原始下载状态分开记录。
