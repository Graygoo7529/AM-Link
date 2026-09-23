# AM-Link

面向 Agent Memory Leaderboard 的智能体记忆研究项目：实现 Add 写入和 Search 证据检索，由主办方统一回答与评分。

**当前阶段：一期归档，二期调研。** 一期 `0.3.0` 已通过官方 Smoke 并完成 Full；用户反馈取得了不错的成绩，尚未在这里登记具体名次和官方分数。2026-09-23 已关闭一期公网 API 并清理服务器部署代码。

AM-Link 和设计灵感来源 **TinySoul-Agent** 都是 Graygoo7529 的个人原创项目。一期借鉴自己的记忆设计思想，独立实现比赛接口，未直接移植 TinySoul-Agent 代码。

| 入口 | 内容 |
| --- | --- |
| [AGENTS.md](./AGENTS.md) | 给后续 agent 的项目背景、环境和简要规约 |
| [docs/README.md](./docs/README.md) | 精简经验、收尾记录和二期接入调研 |
| [archive/phase-1](./archive/phase-1/) | 一期代码、原始设计、历史文档及测试，作为冻结参考 |

一期运行代码基线为 `1881abe`，归档前仓库 HEAD 为 `447608a`。旧文档中的“当前部署”“待 Smoke”等描述是当时记录；当前状态以根目录文档为准。二期实现尚未开始。

## 本地复核一期

Windows / PowerShell，已有根目录 `.venv` 使用 Python 3.13.14。新环境先执行 `python -m venv .venv`，然后在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e "./archive/phase-1[dev]"
Set-Location archive/phase-1
..\..\.venv\Scripts\python.exe -m pytest -q --basetemp B:\tmp\aml-phase1-pytest
```

归档后已复核 61 项测试及依赖检查。[启动与部署经验](./docs/operations/server.md)包含本地启动和 Docker 命令；本地不安装、不运行 Docker。

所有 `data/`、本地参考项目、环境和 `docs/private/` 均由 Git 忽略。私有目录保存经用户授权的服务器凭据与模型配置，仅本机可见。公开仓库：[Graygoo7529/AM-Link](https://github.com/Graygoo7529/AM-Link)。
