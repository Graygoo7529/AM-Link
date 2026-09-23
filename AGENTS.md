# 项目记忆

- AM-Link 是 Graygoo7529 参加 Agent Memory Leaderboard 的原创记忆系统。我们只提供 Add/Search，主办方负责 Answer/Eval。TinySoul-Agent 也是同一作者的个人原创项目，是设计灵感来源。
- 截至 2026-09-23：一期 Smoke 通过、Full completed，在 [AM-Link 排行榜开源榜文本赛道](https://agentmemories.ai/leaderboard/academic/textual)排名第 21 名；一期公网 API、部署代码、数据库数据和专用证书均已清理。服务器现保留与项目无关的通用 Nginx、Certbot renewal 基础和 `/hello` 示例。二期处于调研阶段，还没有新实现。具体收尾状态见 `docs/phase-1/closeout.md`。
- 一期代码在 `archive/phase-1/`，版本 0.3.0；代码基线 `1881abe`，归档前 HEAD `447608a`。保持归档作为历史参考，二期代码应另建目录。
- 每次开始先读根 README、`docs/README.md`、`docs/phase-2/integration-research.md`；只按任务需要读历史长文，不把旧文档的当前状态当成今天的事实。

## 环境

- 工作区 `B:\WorkSpace\AMLeaderboard`，Windows PowerShell，时区 Asia/Shanghai。
- 根 `.venv\Scripts\python.exe` 是 Python 3.13.14，源自 `C:\Anaconda3\envs\common`；一期要求 Python 3.10+。归档后 editable 安装已指向 `archive/phase-1/src`。
- 安装：根目录执行 `.\.venv\Scripts\python.exe -m pip install -e "./archive/phase-1[dev]"`。
- 测试：在 `archive/phase-1` 执行 `..\..\.venv\Scripts\python.exe -m pytest -q --basetemp B:\tmp\aml-phase1-pytest`。此临时目录专供 pytest，勿存放其他文件。
- 本地禁止安装和使用 Docker；确需构建时使用 GitHub Actions 或服务器。旧 workflow 已随一期归档，根目录目前没有自动 CI。
- 当前环境若 Git 提示 dubious ownership，使用单次参数 `git -c safe.directory=B:/WorkSpace/AMLeaderboard ...`；不要为此改全局信任设置。

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

- 每轮完成工作后必须运行 `git -c safe.directory=B:/WorkSpace/AMLeaderboard status --short`、`git diff --check`，并检查是否有未预期的临时文件、凭据或数据库进入工作树。
- 最终回复必须说明未提交内容的范围，区分代码、文档、归档删除和配置变更；如果存在未提交内容，给出可直接使用的建议提交标题和简短提交说明。不要在用户未要求时自动提交或推送。
- 若本轮包含服务器操作，最终回复同时核对服务状态、监听端口、公开 endpoint、systemd 自启动和是否仍有一期路径；远程临时脚本、askpass 文件和测试数据必须清理。

## 一期环境速查

- 服务器：阿里云 ECS `121.43.49.84`，SSH `root` 账号和密码只在被 Git 忽略的 `docs/private/server-access.md`；一期已经停服并删除数据、程序、专用证书和续期配置，后续任务不要自动恢复。
- 一期链路：公网 `HTTPS:443` → Nginx → `127.0.0.1:8080` Uvicorn → SQLite/WAL 与模型提供方。应用曾以 `aml` 用户、单 worker、systemd `aml-memory.service` 运行；历史配置快照在 `docs/private/`。
- LLM：智增增 OpenAI 兼容接口 `https://api.zhizengzeng.com/v1`，模型 `gpt-4o-mini`；embedding：智谱 `https://open.bigmodel.cn/api/paas/v4`，模型 `embedding-3`、512 维。Key 只在 `docs/private/phase1-server.env`，不要复制到公开文档或日志；完整接入说明见 `docs/operations/models.md`。
- 一期接口：`POST /v1/memory/add`（`request_id/messages/user_id/session_id`）和 `POST /v1/memory/search`（`query/options?/user_id/top_k`），Bearer Memory System Key；`GET /health` 无鉴权。Add 只有持久化且可立即 Search 才返回 200；Search 只返回证据。完整字段和错误边界见 `docs/phase-1/lessons.md`。
- 官方重试：按 [API Guide](https://agentmemories.ai/api-guide)，Add 对网络错误、408/409/425/429/500/502/503/504/524 有界重试，Search 对网络错误、408/425/429/500/502/503/504 有界重试；Add 最多 32 次请求尝试，429 遵循 `Retry-After` 最多 60 秒。400/401/403/404/422 等契约或权限错误不重试，200 但响应格式错误也算失败。二期不要再叠加后台补偿队列。
- Key 和 HTTPS：Memory System Key 是我们生成并配置在服务端的 API 访问密钥，官方只用它调用 Add/Search；Eval/Leaderboard Key 由官方签发，仅用于评测平台。生产 URL 使用 HTTPS，证书在 Nginx 终止；一期 IP 证书由 Certbot 续期，部署结束后停止 timer 并删除专用证书。二期重新部署必须重新签发证书、验证 SAN/到期/续期，再提交公网 URL。
- 通用服务器现状：Nginx `nginx.service` 已启用，监听 `80`，`http://121.43.49.84/hello` 和 `/health` 是与 AM-Link 无关的长期示例；`public-certbot-renew.timer` 已启用，每 6 小时检查证书。Let’s Encrypt 自 2026-01 起支持公网 IP 证书，但必须使用 `shortlived` profile，证书约 160 小时有效，Certbot 5.7.0 已支持 `--ip-address`；Nginx 插件尚不能自动安装 IP 证书，需要手工配置 443 和 deploy hook。域名证书仍是长期服务的首选，不要把 HTTP 示例误当作 AM-Link 可提交的 HTTPS 地址。
