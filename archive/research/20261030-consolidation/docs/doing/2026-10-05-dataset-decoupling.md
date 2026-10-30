# 数据层与靶场解耦、公开数据获取

日期：2026-10-05；本轮重构与小样本验证：`done`。全量 LongMemEval、PersonaMem 历史获取仍有网络障碍；真实 AM-Link/Mem0 效果对照尚未运行。

## 用户语义与验收边界

数据集是独立材料，不是待测方法，不需要 AML 专用版本。dataset 应能单独读取、分析、预处理、切分与使用；benchmark 应负责两种适配：数据 → 可重复的评测环境，以及评测环境 → 待测系统的 Add/Search 接口。不能把 Add/Search manifest 作为 dataset 的默认输出。

一期代码保留归档。二期服务仍未实现。本轮只改本地数据工具与靶场，不操作服务器、不获取 Mem0 源码、不安装 Docker，也不读取模型凭据。

## 设计

1. **来源与中立 pack**：统一来源清单；完整原始文件放 `dataset/data/raw`；HF 行快照放 `snapshots`，保留原始响应和获取 receipt；预处理输出 `records/sessions/turns/tasks`，历史、任务输入、标注分开。数据层无 benchmark 导入，也不生成请求 ID、user scope、分块或评分规则。
2. **数据特点保留**：LoCoMo 保留 speaker/participants，由 benchmark 决定协议角色；LongMemEval 保留会话与 turn 注释；ScriptMem 保留选择题及缺失历史状态；CL 系列保留原 messages/instructions 和 rubric，只有确定边界才拆分；PersonaMem 保留外部历史引用；BEAM 仅 chat 为历史，其余生成背景/理想回答不进入历史。
3. **切分**：原始行按 offset/limit 切片；结构化 pack 按 group_id 分 dev/holdout，并固定 seed、输入哈希与分组规则。只有一个来源组拒绝切分。LoCoMo/LongMemEval 会话截断后排除证据不完整的问题。
4. **环境适配**：`benchmark/datasets.py` 将 pack 转为 `evidence-retrieval` 计划。历史分为不超过 20 条消息、2,000 个空白分隔词的 Add；超长 turn 拆成可追踪字符区间。该计数仅为本地规则；record/task/turn → 请求映射与 exclusions 均落盘。
5. **待测对象**：保持 `aml-api / mem0-library / mem0-oss`；目标接收统一 Add/Search，不知道来源格式。真实运行需要用户提供或实现服务/配置。Mem0 仅通过发布包或现成 REST API 访问。
6. **评分与可观测性**：evidence 标注由 benchmark 解释；无 evidence 为 ungraded，不能记成 0 或空检索金标；QA 不可回答不等于必须返回空。答案/rubric 不进入目标请求。plan、逐请求 trace、report 分别记录环境、实际行为与聚合结果。

## 实际数据获取

| 数据源 | 已取得范围与核验 | 剩余限制 |
| --- | --- | --- |
| [LoCoMo](https://github.com/snap-research/locomo) | 既有完整原始 JSON；再次核验 SHA `79fa87e9…`；10 对话、272 会话、5,882 turns、1,986 题 | 图像本体不在作者发布中，文本读取器使用 caption |
| [LoCoMo-Refined](https://github.com/mem-eval-suite/LoCoMo_refined) | 经 GitHub Contents/Blob API 获得固定 commit 的完整 raw JSON（SHA `1aef6da7…`）与 questions JSONL；1,382 题 | 作为独立社区发布使用，无需建立比赛版本对应关系 |
| [ScriptMem](https://github.com/memorax-ai/ScriptMem) | 6 个文件，457 题；本地实际题型为 298 single_choice、123 multi_select、36 ordering | 作者不发布真实剧本历史；原文件的 omission/schema 示例不能当历史回放。宣传中的 6 类能力不是 public `qa_type` 的 3 类作答格式 |
| [CL-bench](https://huggingface.co/datasets/tencent/CL-bench) | 官方 row API 3 条无截断记录，SHA `55c9cce9…` | 2 条单轮任务边界不明，完整保留输入并排除出当前检索环境；1 条多轮可回放 |
| [CL-bench Life](https://huggingface.co/datasets/tencent/CL-bench-Life) | row API 3 条，SHA `1a496b91…`，全部可构建环境 | 此小片仅 Game Logs，不能代表全量类别表现 |
| [PersonaMem-v2](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2) | benchmark_text 3 条，SHA `2486ee88…`，同 persona 521 | 32K 历史引用为作者仓库 `data/chat_history_32k/chat_history_250913_163134_persona521.json`，文件入口 502；无历史时仅做任务读取 |
| [BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) | `100K` split 第 0 行，SHA `4ee087ed…`；3 批次、188 turns、20 probes，10 类各 2 题 | 没有可直接使用的 turn evidence 金标；当前只跑观测，无召回分数 |
| [LongMemEval](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | S/M/Oracle 源与共同读取器已登记 | S/Oracle 完整文件入口失败，行 API 返回 500；读取器仅通过合成结构 fixture，不能写成已验证真实文件 |

普通 raw/HF resolve 下载返回 502；系统 curl 尝试发生证书吊销查询不可达，改用 best-effort 吊销查询后仍在 32 KiB 停滞。失败残片已清理。随后使用正常验证 TLS 的 GitHub 官方 API 成功取得完整文件。HF row API 成功取得的记录均检查 `partial=false`、`truncated_cells=[]`、连续 row_idx，保留原始响应而非复制网页预览。

行 API 服务的是当时缓存数据，不承诺某个仓库 revision；pack 沿用 receipt 的事实，不把 catalog 的完整文件 revision 错套到快照。各文件来源/许可见 [catalog](../../dataset/catalog.json)；LoCoMo/ScriptMem 为 CC BY-NC，CL 系列 evaluation-only，PersonaMem CC BY，BEAM CC BY-SA。原始材料和派生内容均不进入 Git。

## 实施与核对

| 状态 | 事项 | 证据 |
| --- | --- | --- |
| done | 中立 pack 与统一来源清单 | `dataset/pack.py`、`catalog.json`，无 Add/Search 字段 |
| done | 来源读取、分析、切片、分组拆分 | `prepare.py`、`split.py`；保留答案/历史隔离、输入哈希与组身份 |
| done | 可重现获取路径 | `fetch.py`：直接文件、GitHub API、HF rows；内容哈希与 receipt |
| done | 靶场环境适配与离线 plan 命令 | `benchmark/datasets.py`、`python -m benchmark plan` |
| done | 可观测性迁移 | run 产物移到 `benchmark/data/runs`；trace Add 含原始 turn/字符区间；无 gold evidence 时 inspect 可显示全部历史 Add |
| done | 修正数据与评分问题 | LoCoMo 类别映射改为 1 multi-hop、2 temporal、3 open-domain、4 single-hop；MRR 分母纳入未命中题；QA abstention 不再自动充当空检索标签 |
| done | Windows CLI 结构化输出 | stdout 固定 UTF-8；本地 subprocess 可解析包含非 ASCII 原文的 inspect JSON |
| done | 真实小样本 → pack → plan | 下表；完整 QA 答案未流入 Add/Search |
| done | 本地 HTTP 管线验证 | 临时标准库对象，5 Add、3 Search 成功，inspect 关联 2 个 source Add；服务已关闭；仅验证管线，不作为 AM-Link/Mem0 效果 |

| 计划文件（`benchmark/data/plans/`） | cases | Add | Search | 有 evidence 的题 | 排除项 |
| --- | ---: | ---: | ---: | ---: | ---: |
| locomo-smoke.json | 1 | 5 | 6 | 6 | 0 |
| locomo-refined-smoke.json | 1 | 5 | 6 | 6 | 0 |
| clbench-smoke.json | 1 | 6 | 1 | 0 | 2 |
| clbench-life-smoke.json | 3 | 22 | 3 | 0 | 0 |
| beam-smoke.json | 1 | 38 | 10 | 0 | 0 |

全量 LoCoMo 额外验证：原始 1,986 题中，`conv-42/qa-58` 引用不存在的 `D10:19`，`conv-47/qa-38` 引用不存在的 `D4:36`。pack 保留 1,984 题，具体排除原因写入 `preparation.excluded_tasks`；原始文件不修改。对话级 dev/holdout 实际切分为 8/2，未跨组。

代码测试：数据层 12 项、靶场 16 项通过；覆盖错误 blob hash、截断快照拒绝、流式数组完整性、group 不泄漏、标注隔离、缺历史拒绝、长消息来源位置与 MRR 分母。CLI help、plan、split、inspect 和 compileall 通过；12 份获取 receipt 逐一复算 SHA 一致。每次 run 额外保存 dataset-pack 快照，防止原准备文件重建后无法复核。

收尾：`git status --short` 与 `git diff --check` 已检查；51 个数据/派生产物全部由 `data/` 规则忽略，没有 `.partial` 残片、凭据或数据库进入待提交文件。未提交范围为数据/靶场代码与测试、来源清单配置、文档和索引；无一期归档删除、部署配置变更或远程操作。没有提交或推送。

## 后续工作边界

- `pending_external`：LongMemEval 实际数据、PersonaMem 对应历史下载；网络可用后沿相同登记入口继续，不通过答案/相关片段重造历史。
- `todo`：CL-bench 单轮 context/task 的可靠分界，需人工标注边界或来源额外字段；不在 reader 猜测。
- `todo`：统一 Answer 和来源专用 Eval/rubric judge，固定模型/提示词/预算后才比较端到端质量；当前字面 evidence 匹配会低估正确摘要，不能用它给 Mem0 作最终质量排名。
- `todo`：增量检查点、更新与干扰历史等环境 profile；独立于数据读取器迭代。
- `pending_target`：接入实际二期 AM-Link 与配置好的 Mem0 发布包，记录真实 latency/usage/cost；本轮未安装框架、未调用模型。

这些后续事项不影响本轮中立数据层、环境适配、获取路径和本地可观测管线的使用。旧 2026-10-04 文档中的 dataset manifest 设计由本文取代。
