# 项目记忆

- AM-Link 是 Graygoo7529 参加 Agent Memory Leaderboard 的原创记忆系统。我们只提供 Add/Search，主办方负责 Answer/Eval。TinySoul-Agent 也是同一作者的个人原创项目，是设计灵感来源。
- 截至 2026-09-23：一期 Smoke 通过、Full completed，在 [AM-Link 排行榜开源榜文本赛道](https://agentmemories.ai/leaderboard/academic/textual)排名第 21 名；一期公网 API、部署代码、数据库数据和专用证书均已清理。服务器现保留与项目无关的通用 Nginx、Certbot renewal 基础和 `/hello` 示例。二期初版已归档到 `archive/phase-2/amlink-0.1.0/`；当前 `amlink/` 是 0.2.1，2026-10-11已实施核心工程修复并完成有限真实诊断；方法质量和完整协调器仍待验收，尚未部署或参加官方 Smoke。具体收尾状态见 `docs/phase-1/closeout.md`。
- 一期代码在 `archive/phase-1/`，版本 0.3.0；代码基线 `1881abe`，归档前 HEAD `447608a`。保持归档作为历史参考，二期代码应另建目录。
- 每次开始先读根 README、`docs/README.md`、`docs/phase-2/integration-research.md`；只按任务需要读历史长文，不把旧文档的当前状态当成今天的事实。
- 统一研究展示入口是 `visualization/README.md`，覆盖数据构成、样本标注、理论链路与运行观测；`casestudies/` 留在根目录保存案例文档与唯一案例 catalog，两个视图共用它。网页 `index.html` 与会话片段 `view.html` 同源生成，原文/轨迹只进入忽略的 `visualization/data/`。用户不需要保存页面选择状态。
- 根目录 `DESIGN.md` 是 AM-Link Add/Search 当前设计总览；修改二期链路、边界或案例结论时及时更新，并明确区分已实现、实测与待验证。实现细节仍以 `amlink/` 源码和 README 为准。
- `docs/phase-2/method-improvement-plan.md` 是 2026-10-11 的二期重构设计与执行计划，当前状态为“0.2.1 工程修复已实施，方法质量继续验证”；以下为目标语义（不代表全部已实现）：向量/select 默认开启、select 同时筛选排序、`episode` 承担高保真情景日志、Reflection Workspace 跨 Add 延续，Reflection 按积累阈值/硬信号/会话边界触发（不是每次 Add），模型决定额外 Mutation 或真正 no-op。每个成功 Add 先生成一个保留角色、顺序、会话和原文语境的最小 `episode`，完成 BM25 与向量索引后才返回 200；这保证立即可检索，同时不要求每个 Add 都调用 Reflection。标准 Search 每次新建独立语境，只检索结构化 MemoryItem（包括最小 episode），不直接读取 WorkingMemory，也不与 Reflection 共用 loop；首个 Search 不需要排空或处理 WorkingMemory 尾部。API tool calling 优先、过程可观测、模型按 References 选择 Inspect/Backlink 参数、不设固定 kind 准入闸门、答案辅助明确延后；不引入 `seed_refs` 主语义。模型可见语境有明确的字符预算投影，Select 另有候选预算，完整观测保留截断原因。后续继续区分实现、实测和待验证。
- 2026-10-11 核心审计见 `docs/doing/2026-10-11-amlink-core-audit.md`：已触发Reflection同步完成后才返回，但并发协调器/持续Workspace/Reflection多跳未按计划落实；当前输入预算仍可复现超限。100题主实验Add41/145、Search92/100，148个episode、4个event、0边；29个最低episode被摘要覆盖且未更新向量；Select顺序被装箱重排，来源日期未输出。39项测试仅含4项当前方法测试。此前“全部done”“预算已解决”已撤回；待按修订计划修复后重新实测。
- 2026-10-11后续修复见 `docs/doing/2026-10-11-amlink-core-repairs.md`：52项回归通过；旧1445条积压在副本中用替身模型分48批消费，整包最大74596字符。Add期限1740秒含排队，稳定分批并逐请求确认完成；保护最低episode、全部改变节点重嵌入、Workspace跨批保留、Reflection接入Inspect/Backlink、Select只用question+候选叙事并分页后统一精炼、保留顺序、传递来源日期、去重证据。4个真实窗口切片12 Add/4 Search成功，但L04只有6/7标注覆盖且派生节点存在主体/来源错误；Reflection真实尚未调用图工具。旧图Search局部诊断仍有预览漏证据及集合召回退步。不能宣称图质量或整体效果已修好；无内部重试、无部署、未实现完整并发追加协调器。
- AM-Link 二期埋点遵循 `benchmark/OBSERVABILITY.md`；`observability.py` 提供标准事件校验与 recorder。未采集是未知，理论方案与实测分开；已接入 `amlink.native:factory` 并记录真实模型切片；HTTP 服务默认不采集内部轨迹。
- 2026-10-08 靶场增加 `python -m benchmark answer`：只读取真实 Search 问题与返回内容，运行 `gpt-5.6-luna` 诊断回答，并将 Answer、模型调用和后验人工 eval span 持久接入可视化。它不是 AM-Link API；正式比赛仍由主办方执行 Answer/Eval。案例与限制见 `docs/doing/2026-10-08-amlink-answer-research.md`。
- 2026-10-07 研究已扩至 26 个案例、四视角（设计检查并入理论）。`benchmark/STUDIES.md` 是案例/数据切片运行、native 埋点、自动展示与持久评注入口；案例数据绑定仅存于 catalog，运行档案在忽略的 `benchmark/data/research/workspace.json`，重载用 `visualization.build --local --workspace --web`。实施见 `docs/doing/2026-10-07-research-infrastructure.md`。
- 全量结构、BM25 与 Mem0 六条件实测见 `docs/doing/2026-10-07-dataset-research.md`。`casestudies/mem0-microstudy.md` 记录真实短例结果与局限；已有轨迹可以直接加载，不必重跑模型，不把短例结果当成全量准确率。2026-10-08 又完成 6 个跨数据集切片和 1 个 BEAM 冲突重跑，归纳见 `docs/doing/2026-10-08-memory-research-survey.md`。
- 2026-10-08 二期本地实现与验证见 `amlink/README.md` 和 `docs/doing/2026-10-08-amlink-implementation.md`。此前 91 项二期方法测试通过；本轮靶场/方法/可视化联合测试 71 项通过。新增 7 个真实 AM-Link 切片、8 个 `gpt-5.6-luna` 回答及后验核对见 `docs/doing/2026-10-08-amlink-answer-research.md`：金额、比例、拒答案例正确；时间计量、复合答案完整性和冲突表达仍有缺口。L01/LM01/P02/PV04 在 reflection schema/关系校验阶段阻断 Add/Search，不能评价其 Answer 或遗忘效果。B02 已检索到互相冲突的来源，但回答仍先肯定再保留。靶场适配器 v2 会把真实 speaker 加入消息正文，旧运行不自动改变。
- reference\TinySoul-Agent 是我进行的另一个项目，可以探索和参考它使用的记忆设计理念和 Inspect、Search 原型方法

## 环境

- 工作区 `B:\WorkSpace\AM-Link`，Windows PowerShell，时区 Asia/Shanghai。
- 根 `.venv\Scripts\python.exe` 是 Python 3.13.14，源自 `C:\Anaconda3\envs\common`；一期要求 Python 3.10+。归档后 editable 安装已指向 `archive/phase-1/src`。
- 安装：根目录执行 `.\.venv\Scripts\python.exe -m pip install -e "./archive/phase-1[dev]"`。
- 测试：在 `archive/phase-1` 执行 `..\..\.venv\Scripts\python.exe -m pytest -q --basetemp B:\tmp\aml-phase1-pytest`。此临时目录专供 pytest，勿存放其他文件。
- 本地禁止安装和使用 Docker；确需构建时使用 GitHub Actions 或服务器。旧 workflow 已随一期归档，根目录目前没有自动 CI。
- 当前环境若 Git 提示 dubious ownership，使用单次参数 `git -c safe.directory=B:/WorkSpace/AM-Link ...`；不要为此改全局信任设置。

## 简要规约

- 文档以中文为主，简短、可读；记录已验证事实、判断和待验证问题，不把计划写成已完成。维护文档索引和收尾状态，完成事项标记 `done`。
- 原文和来源可追溯、按 user_id 隔离、Add 幂等且成功后立即可检索；Search 输出证据，不能代答。
- 二期默认采用请求内有界工作和显式错误，交给官方做约定内的重试。不要继承一期后台补偿队列、自动整用户重建或多层模型重试。任何例外要有实测收益和明确成本边界。
- 模型故障不能伪装成“成功但没记忆”；无结果与依赖失败必须区分。成功幂等重放不再调用模型；失败重放应能完成尚未完成的必要工作。
- 公开小样本检验后再扩大规模，分别报告召回质量、完整证据链、延迟、实际模型调用与费用。不要根据 HTTP 200 推断所有增强成功。
- `data/`、数据库、`references/`、私有凭据不可提交。服务器账号和模型 Key 在被忽略的 `docs/private/`，按任务需要读取，避免输出秘密。此前已授权 SSH 维护；一期已下线，后续任务未要求部署时不要自行恢复服务。
- 二期模型限制存在官网文案差异，见调研文档；不得假定一期 Key、模型约束、超时或配额自动适用于二期。
- 不改用户无关内容；不主动派生子 agent，除非用户明确要求。

## 每轮结束检查

- 每轮完成工作后必须运行 `git -c safe.directory=B:/WorkSpace/AM-Link status --short`、`git diff --check`，并检查是否有未预期的临时文件、凭据或数据库进入工作树。
- 最终回复必须说明未提交内容的范围，区分代码、文档、归档删除和配置变更；如果存在未提交内容，给出可直接使用的建议提交标题和简短提交说明。不要在用户未要求时自动提交或推送。
- 若本轮包含服务器操作，最终回复同时核对服务状态、监听端口、公开 endpoint、systemd 自启动和是否仍有一期路径；远程临时脚本、askpass 文件和测试数据必须清理。

## 一期环境速查

- 服务器：阿里云 ECS `121.43.49.84`，SSH `root` 账号和密码只在被 Git 忽略的 `docs/private/server-access.md`；一期已经停服并删除数据、程序、专用证书和续期配置，后续任务不要自动恢复。
- 一期链路：公网 `HTTPS:443` → Nginx → `127.0.0.1:8080` Uvicorn → SQLite/WAL 与模型提供方。应用曾以 `aml` 用户、单 worker、systemd `aml-memory.service` 运行；历史配置快照在 `docs/private/`。
- LLM：智增增 OpenAI 兼容接口 `https://api.zhizengzeng.com/v1`，模型 `gpt-4o-mini`；embedding：智谱 `https://open.bigmodel.cn/api/paas/v4`，模型 `embedding-3`、512 维。Key 只在 `docs/private/phase1-server.env`，不要复制到公开文档或日志；完整接入说明见 `docs/operations/models.md`。
- 一期接口：`POST /v1/memory/add`（`request_id/messages/user_id/session_id`）和 `POST /v1/memory/search`（`query/options?/user_id/top_k`），Bearer Memory System Key；`GET /health` 无鉴权。Add 只有持久化且可立即 Search 才返回 200；Search 只返回证据。完整字段和错误边界见 `docs/phase-1/lessons.md`。
- 官方重试：按 [API Guide](https://agentmemories.ai/api-guide)，Add 对网络错误、408/409/425/429/500/502/503/504/524 有界重试，Search 对网络错误、408/425/429/500/502/503/504 有界重试；Add 最多 32 次请求尝试，429 遵循 `Retry-After` 最多 60 秒。400/401/403/404/422 等契约或权限错误不重试，200 但响应格式错误也算失败。二期不要再叠加后台补偿队列。
- Key 和 HTTPS：Memory System Key 是我们生成并配置在服务端的 API 访问密钥，官方只用它调用 Add/Search；Eval/Leaderboard Key 由官方签发，仅用于评测平台。生产 URL 使用 HTTPS，证书在 Nginx 终止；一期 IP 证书由 Certbot 续期，部署结束后停止 timer 并删除专用证书。二期重新部署必须重新签发证书、验证 SAN/到期/续期，再提交公网 URL。
- 通用服务器现状：Nginx 已启用，监听 `80/443`；`https://121.43.49.84/hello` 和 `/health` 是与 AM-Link 无关的示例，HTTP 仍可用。Certbot 5.7.0 已签发 Let’s Encrypt 生产 IP 证书，lineage 为 `public-ip`，使用 `--ip-address`、`--required-profile shortlived` 和 webroot `/var/www/certbot`；证书约 160 小时有效。`public-certbot-renew.timer` 每 6 小时检查，续期成功后先 `nginx -t` 再 reload；续期服务限时 5 分钟，并检查证书至少剩余 48 小时（失败写 systemd/journal，尚无外部告警）。2026-09-23 已验证公网 TLS、SAN/信任链、续期 dry-run 和 deploy hook；实际到期以服务器当前证书为准，不能沿用文档日期。维护见 `docs/operations/server.md` 与服务器 `/opt/public-web/README.md`。
