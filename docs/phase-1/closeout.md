# 一期收尾记录

日期：2026-09-23。用户确认一期比赛已完成；官方 Smoke 通过、Full completed。一期在 [AM-Link 排行榜开源榜文本赛道](https://agentmemories.ai/leaderboard/academic/textual)排名第 21 名。

## 冻结与归档

- 一期版本 `0.3.0`，运行代码基线 `1881abeb71b1704bbd64f1287ef830f8806c0bff`。
- 归档前 HEAD `447608ad7578e831e75609cf92e04f89580b42e0`；后者是 README 修改。
- 原工作树干净；迁移了源码、测试、配置、Dockerfile、workflow、原设计文档、历史 docs、data 和 references 到 `archive/phase-1/`。
- 46 个原受版本控制文件的迁移前后 SHA-256 全部一致。历史文件保留原样，所以旧文档的“当前实例”“待办”不是今天的状态。
- `.git` 和本地 `.venv` 留在根目录，Git 历史未重写；editable 安装已更新到归档路径。未建立第二份嵌套仓库。
- 根目录重新建立 README、AGENTS 和 docs。原 workflow 在归档内部，不再触发自动构建。

## 执行状态

| 状态 | 事项 | 结果 |
| --- | --- | --- |
| done | 关闭一期接口 | 一期应用与 8080 监听已关闭；后续启用通用 80/443 示例，旧 Add/Search 返回 404，新的 health 仅表示通用 Nginx 状态 |
| done | 停止后台及自动启动 | 一期 API 与旧 Nginx 站点禁用自启；一期证书续期 timer 停止并移除（通用 Nginx 后续重新启用） |
| done | 保存部署经验 | 环境及 systemd/Nginx 快照取回本地 `docs/private/`，已验证 Git 忽略 |
| done | 删除部署代码与密钥环境文件 | 删除 `/opt/aml-memory`、`/etc/aml-memory.env` 和专属服务/站点配置；Nginx 配置检查通过 |
| done | 一期服务器数据及备份 | 删除 `/var/lib/aml-memory` 及其中 SQLite、WAL、Markdown 和旧备份；服务器不再保留一期评测数据 |
| deferred | 主机级访问日志 | `/var/log/nginx` 与 `/var/log/letsencrypt` 可能包含一期请求，但无法证明整份文件只属于 AM-Link；未删除，避免影响服务器其他服务 |
| done | 本地归档及 ignore | 46/46 文件一致；data、数据库、references、私有资料均忽略 |
| done | 修复本地运行路径 | 根 `.venv` 可正确导入归档中的 `aml_memory` 0.3.0 |
| done | 验证归档 | 61 项测试通过、pip check 通过；一条 TestClient 依赖弃用警告 |
| done | 经验沉淀与二期调研 | 文档入口、设计理念、实验/架构复盘、运维/模型经验及二期调研 |
| done | 通用服务器基础 | Nginx 开机服务、HTTP/HTTPS hello/health 示例、通用 Certbot renewal timer 和 `/opt/public-web/README.md` 已建立；与一期 API 解耦 |
| done | 通用 IP HTTPS | 新签发 `public-ip` shortlived 生产证书，启用 443；公网 TLS、IP SAN/信任链、续期 dry-run 与 reload hook 均验证通过 |

首次 pytest 已完成用例，但清理旧系统临时目录时权限失败；改用独立 `B:\tmp` 临时目录后完整退出成功。没有为解决环境权限修改归档代码，也没有执行付费模型调用。

## 保存与不保存

本地 `archive/phase-1/data/` 保存一期原有数据目录，以及从本机临时目录找回的公开 LoCoMo 数据、回放 manifest 和实验报告；它们均不进入 Git。没有把服务器正式评测数据库下载为二期训练或调参数据。

服务器保留与 AM-Link 无关的通用 Nginx 和 Certbot renewal，提供 `https://121.43.49.84/hello` 与 `/health` 示例，HTTP 也可用；一期专用证书 lineage、续期配置、数据库、Markdown 数据和旧备份均已删除。新的通用 IP 证书单张约 160 小时有效，每 6 小时检查续期；具体维护和验证见[服务器接入经验](../operations/server.md)。主机级 Nginx/Certbot 日志因可能由其他服务共享而保留，见上表。ECS 实例尚未释放，云资源费用与 API 是否运行是两件事。

归档基础已记录在提交 `59e2cc7`（`Archive 1`）；后续提交状态以 `git status` 和提交历史为准。下次会话以根 [AGENTS.md](../../AGENTS.md) 和 [docs 索引](../README.md) 恢复工作上下文。
