# 手动补齐数据

核对日期：2026-10-05。链接是作者发布页或文件入口；页面可读不代表本机已完成下载。大小为页面显示的约数。`main` 可能变化，取得文件后需记录当时 revision、来源 URL 和 SHA-256。

## 已完整取得的范围

- LoCoMo：完整文本 JSON；原始图片未发布在该仓库，本机只有 caption 等文本。
- LoCoMo-Refined 社区版：当前固定版本的完整历史与问答；不等于 AML 私有冻结包。
- PerLTQA：完整中文 memory/QA。英文版未下载，本次不把“中文完整”写成整个双语项目完整。
- ScriptMem：公开的 457 题已齐；完整实验仍缺剧本，作者不随仓库发布，无法给出官方剧本直链。

## 可手动下载的缺口

| 数据集 | 当前本机 | 下载入口与应取内容 | 建议顺序 |
| --- | --- | --- | --- |
| LongMemEval | S/M/Oracle 均无真实文件 | [S，约 277 MB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_s_cleaned.json?download=true)；[Oracle，约 15.4 MB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_oracle.json?download=true)；[M，约 2.74 GB](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/98d7416/longmemeval_m_cleaned.json?download=true)；[文件页](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/main) | 优先 S；Oracle 可诊断答案端，不能替代完整长历史 |
| CL-bench | 3 / 1,899 条 | [CL-bench.jsonl，约 90.1 MB](https://huggingface.co/datasets/tencent/CL-bench/resolve/66122c88771ac4f09f163415902828b933e78899/CL-bench.jsonl?download=true)；[文件页](https://huggingface.co/datasets/tencent/CL-bench/tree/main) | 优先 |
| CL-bench Life | 5 / 405 条 | [CL-bench Life.jsonl，约 29.3 MB](https://huggingface.co/datasets/tencent/CL-bench-Life/resolve/cd2589f/CL-bench%20Life.jsonl?download=true)；[文件页](https://huggingface.co/datasets/tencent/CL-bench-Life/tree/main) | 优先 |
| BEAM | 100K 档 2 / 20 条；500K、1M 未取得 | [100K，约 5.43 MB](https://huggingface.co/datasets/Mohammadta/BEAM/resolve/3205395/data/100K-00000-of-00001.parquet?download=true)；[全部三档文件，约 106 MB](https://huggingface.co/datasets/Mohammadta/BEAM/tree/main/data) | 先补 100K |
| BEAM-10M | 未下载 | [两个 parquet 分片，共约 344 MB](https://huggingface.co/datasets/Mohammadta/BEAM-10M/tree/main/data)，完整使用需两个分片 | 压力测试时再取 |
| PersonaMem-v2 | 仅 3 道文本题；无对应历史 | [benchmark.csv，约 42.4 MB](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/e3a5916/benchmark/text/benchmark.csv?download=true)＋[32K 历史目录](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/tree/main/data/chat_history_32k)；更长输入另取 [128K 历史](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/tree/main/data/chat_history_128k) | CSV 必须配套其引用的历史；只下问题不能回放 |
| MemoryAgentBench | 未取得真实样本 | [四类 parquet，约 74.8 MB](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/tree/main/data)；先取 Conflict_Resolution（约 1.49 MB）和 Test_Time_Learning（约 3.95 MB）；完整包另含 [entity2id.json](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/blob/main/entity2id.json) 和 README | 新能力候选；尚未适配读取器 |
| PersonaMem-v3 | 尚未下载 | [作者文件页，约 1.95 GB](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3/tree/main)；按 [数据卡](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v3) 配套获取 profiles、context、queries，保留目录结构 | 后续扩展；尚未适配读取器 |

PersonaMem-v2 文本实验不需要先下载 multimodal 目录或 train.csv。现有三题属于 persona 521，可先补 [这一个 32K 历史文件](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/main/data/chat_history_32k/chat_history_250913_163134_persona521.json?download=true)。这些历史位于 Hugging Face 数据仓库，不能将路径接到 GitHub 代码仓库。

补充范围：PerLTQA [英文版](https://github.com/Elvin-Yiming-Du/PerLTQA/tree/8d9e19868e239740ef701e603ec205cd581f221b/Dataset/en)及 [en_v2](https://github.com/Elvin-Yiming-Du/PerLTQA/tree/8d9e19868e239740ef701e603ec205cd581f221b/Dataset/en_v2) 均未下载；如研究双语再取。ScriptMem [作者说明](https://github.com/memorax-ai/ScriptMem)解释了剧本缺口；LongMemEval-Refined 的 AML 冻结包也没有可核验的独立公开下载入口。

## 下载后放在哪里

统一放到 `dataset/data/manual/<数据集名称>/`，保持原文件名及目录结构；该目录已被 Git 忽略。同时保存来源 URL（例如写在同目录 `source.txt`）和下载日期。有多个版本时另建版本子目录，不覆盖当前 raw 文件。

后续让我读取这个目录即可：先辨别 JSON/JSONL/CSV/Parquet 的真实内容与完整性、记录版本/哈希/许可，再转换为当前 pack。现有通用读取器支持 JSON/JSONL/CSV；Parquet 需要额外解码后接入，不能只改扩展名。文件“已下载”、转换“成功”和记忆效果“已验证”分别记录。

这轮只整理手动入口，没有把这些缺口改成下载完成。完整第三方数据不进入 `casestudies/` 或 Git。
