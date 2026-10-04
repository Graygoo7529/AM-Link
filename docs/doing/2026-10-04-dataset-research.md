# 官方数据集和来源核验

日期：2026-10-04；状态：`done`
方法：以 AML 官方 Cycle 2 文档、公开评测仓库和每个上游项目资料为来源。平台公布的名称和公开原始项目名称按不同版本记录，不将同名当作相同 bundle。

## 官方组织方式

Cycle 2 文本任务覆盖长对话、跨会话事实/关系、时间更新、个性化、规则、治理及 Streaming。官方公开页面列出下表中的七个文本基准卡；公开机器 contract 使用粗粒度 ID。官方 AML 仓库另说明文本覆盖已超过 10 个基准，所列公开示例并非完整私有套件。代码和多模态任务独立于文本套件。

| 赛道 | 官方基准名 | 公开 contract ID | 上游与可用性 | 本地使用结论 |
| --- | --- | --- | --- | --- |
| 文本 | LoCoMo-Refined | `locomo` | [SNAP LoCoMo](https://github.com/snap-research/locomo) 有原始 `locomo10.json`；CC BY-NC 4.0 | 可先分析/跑公开原始集；不得称作 AML Refined 套件 |
| 文本 | ScriptMem | `scriptmem` | [MemoraX ScriptMem](https://github.com/memorax-ai/ScriptMem) 公开 457 道题及答案协议，CC BY-NC 4.0；原始影视剧本文本不发布 | 可分析题型/公开 QA 格式，缺少 Add 历史源文本，不能做完整记忆摄取回放 |
| 文本 | LongMemEval-Refined | `longmemeval` | AML 使用适配平台流程的版本；平台完整私有包不公开 | 与上游源和 LongMemEval-S 分开记录 |
| 文本 | LongMemEval-S | `longmemeval` | [作者 Hugging Face 清理集](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)公开 `longmemeval_s_cleaned.json`，MIT；500 questions，文件约 277 MB | 首个 LoCoMo 版本之后优先转换；逐问 haystack 需要很大切片预算 |
| 文本 | CLBench | `clbench` | [CLBench](https://www.clbench.com/) / AML 的公开配置入口提供任务契约；实际源文本和使用许可应逐项核对 | 当前只登记源入口；核明可下载 shard、许可和评测 reader 后再取数 |
| 文本 | PersonaMem-v2 | `personamem_v2` | [Penn PersonaMem-v2](https://github.com/bowen-upenn/PersonaMem-v2) 有公开 benchmark 材料；不同 README 描述的 query/persona/shard 数量不完全一致 | 适合偏好提取与更新；冻结使用前固定源 revision、split、字段及许可 |
| 文本 | BEAM | `beam` | [BEAM](https://github.com/mohammadtavakoli78/BEAM) 原始数据和评估资料公开；项目单独注明 benchmark CC BY-SA 4.0、代码 MIT | 适合后续多尺度长上下文压力测试，不将代码许可套用于数据 |
| 多模态 | ATM-Bench | 当前 contract 未列 | [作者项目](https://github.com/JingbiaoMei/ATM-Bench) | 需图/视频等素材和多模态 Add/Search；仅所选多模态赛道再调研许可、大小和预处理 |
| 多模态 | Mem-Gallery | 当前 contract 未列 | [作者项目](https://github.com/YuanchenBei/Mem-Gallery) | 图集检索/ F1 任务，先保留来源；不下载图像数据 |
| 代码 | CAMBench Coding | 当前文本 contract 未列 | 官方文档列出当前正式计分的 150 个基础软件任务，relevant/noisy 两种条件共 300 次 | 只在代码赛道另建协议与权限检查，不以文本语料近似 |
| 代码 | SWEContextBench | 当前文本 contract 未列 | [作者项目](https://github.com/jiayuanz3/SWEContextBench) | 官方标记为参考目录，当前不作为 AML 代码赛道计分集 |

`personamem_v1` 仍存在于 2026-09-23 本地机器 contract 快照，与当前官网页面突出显示的 PersonaMem-v2 不一致；保留它作为旧快照的字段，正式数据名单以本次冻结 contract 为准。当前公开文本卡列表中 LongMemEval-Refined 与 LongMemEval-S 也分开出现，而机器 contract 将二者映射到一个 `longmemeval` ID。

官方 AML 仓库可公开浏览各数据集的配置和评分适配，但明确排除 benchmark corpora、held-out questions、gold answers、rubrics、private annotations、participant run artifacts 和 production logs。故官网的数据卡只能证明其纳入的任务类别，不能据此推断隐藏语料、题量、SHA 或官方 reader。Streaming 是文本赛道能力要求，不是当前公开列表中的独立数据集。

## 可比较性和用途限制

- 公开上游原始数据仅作为本地 Add/Search 检索诊断。LoCoMo、LongMemEval-S 名称相近也不是 AML 的正式打包版本、题目映射、统一答案模型或 judge 输出。
- ScriptMem 缺原脚本正文，不能把问答/选项/答案填成输入记忆；否则会泄漏答案，也测不到 Add/Search 对历史的处理。
- LongMemEval 的官方公开测量含 Answer+QA judge；本靶场的 evidence-session recall 只是输入检索视图，不能代替完整 QA accuracy。
- 上游 raw data 和 derived manifests/trace 都带许可归属并留在本机忽略目录。不要以公开原始数据推断 AML hidden data，也不要向 Mem0/cloud 或外部 provider 发送数据，除非明确选择并配置这样的服务。
- 若实际取得 AML 受限评测副本，应严格遵守其任务范围、访问权限和删除期限；不要将其纳入这次 public-data workspace。

## 资料来源

- [AML Cycle 2 用户文档与基准卡/API 合约](https://agentmemories.ai/zh-cn/docs)；检索日期 2026-10-04。
- [AML 公开评测发布仓库](https://github.com/AML-memory/agent-memory-leaderboard)及[中文 README](https://github.com/AML-memory/agent-memory-leaderboard/blob/main/README_CN.md)；该仓库公开数据集配置而不含实际语料、held-out 标注和参评运行产物。
- [LongMemEval upstream README](https://github.com/xiaowu0162/LongMemEval) 和[Hugging Face 数据卡](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned)；源记录约 500 问、S 版约 115K tokens/问，评测默认看 gold answer sessions；数据许可以清理集 MIT 卡和作者版本为准。
- [Mem0 自托管开源 REST API 文档](https://github.com/mem0ai/mem0/blob/main/docs/open-source/features/rest-api.mdx)：`POST /memories`、`POST /search`；与其托管平台 `/v1/` 或 `/v3/` 路径不同。
- [Mem0 仓库 LICENSE](https://github.com/mem0ai/mem0/blob/main/LICENSE)：当前主分支代码许可 Apache-2.0；被测实例的模型、向量库、数据仍需各自核验。
