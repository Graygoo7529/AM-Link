# 项目记忆

- AM-Link 是 Graygoo7529 参加 Agent Memory Leaderboard 的原创记忆系统。我们只提供 Add/Search，主办方负责 Answer/Eval。TinySoul-Agent 也是同一作者的个人原创项目，是设计灵感来源。
- 截至 2026-09-23：一期 Smoke 通过、Full completed，已关闭公网一期服务并清理部署代码；二期处于调研阶段，还没有新实现。具体收尾状态见 `docs/phase-1/closeout.md`。
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
