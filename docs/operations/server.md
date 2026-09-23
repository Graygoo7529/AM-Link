# 服务器接入经验

2026-09-23 已停止一期 API、Nginx 和专属证书续期任务，并清理项目部署。以下是复用经验，不表示旧地址仍可调用。

## 一期部署链路

```text
本地源码 -> 构建 wheel -> SSH/SCP 上传 -> 服务器 venv 安装
公网 HTTPS :443 -> Nginx -> 127.0.0.1:8080 Uvicorn -> SQLite + 外部模型
```

服务器是阿里云 ECS，IP `121.43.49.84`。通过系统 OpenSSH 的 `ssh` 和 `scp` 对接；登录资料在本地 `docs/private/server-access.md`。本地无交互会话曾用临时 SSH_ASKPASS 脚本提供已授权密码，操作后删除脚本；复杂远程命令先写成 LF 换行脚本再上传，避免 PowerShell 与 Bash 双重展开。

应用使用独立 `aml` 用户、单个 Uvicorn worker 和 systemd 托管；SSH 管理用户与应用运行用户不同。以前的路径为：

| 路径/服务 | 用途 |
| --- | --- |
| `/opt/aml-memory/app`、`/opt/aml-memory/venv` | 工作目录和应用依赖 |
| `/etc/aml-memory.env` | systemd 注入的环境配置，权限 600 |
| `/var/lib/aml-memory` | SQLite、WAL、Markdown 派生记忆及旧备份 |
| `aml-memory.service` | 启动、故障重启及应用权限约束 |
| Nginx 80/443 | HTTP 跳转 HTTPS、TLS 终止、转发 loopback API |

无需域名也曾成功部署 IP HTTPS。一期使用短期 IP 证书，靠 Certbot 每 6 小时检查续期来维持可用；**单张证书不覆盖 30 天，连续可用依赖续期链路**。二期重新部署时应重新核验当时的证书产品与规则，签发/更新证书，检查 SAN、到期时间、续期 dry-run 和重载钩子，不沿用“证书应该还有效”的假设。

Nginx 原配置为请求体 4 MiB、连接超时 10 秒、收发超时 180 秒。它们是一期部署取值，不是二期标准；尤其不能直接用来承接二期多模态请求。服务器安全组与本机监听都必须检查；应用 8080 保持 loopback 即可。

## 本地与 Docker 复核

根目录虚拟环境已指向归档。下列命令在 `archive/phase-1` 执行，只启动无外部模型的本机实例：

```powershell
$env:AML_AUTH_SCHEME = 'none'
$env:AML_DB_PATH = 'B:\tmp\aml-phase1-local.db'
$env:AML_MARKDOWN_VIEW_DIR = 'B:\tmp\aml-phase1-local-markdown'
$env:AML_LLM_ENABLED = 'false'
$env:AML_EMBEDDING_ENABLED = 'false'
..\..\.venv\Scripts\python.exe -m aml_memory
```

默认地址 `http://127.0.0.1:8080`，检查 `GET /health`。配置不会自动从 `.env.example` 加载。结束实验后停止进程；需要真实模型时见[模型接入](./models.md)。

Docker 只在支持 Docker 的远端或 CI 使用；同样从 `archive/phase-1` 构建：

```bash
docker build -t aml-memory:0.3.0 .
docker run --rm -p 127.0.0.1:8080:8080 -v aml-phase1-local:/data \
  -e AML_AUTH_SCHEME=none -e AML_LLM_ENABLED=false \
  -e AML_EMBEDDING_ENABLED=false aml-memory:0.3.0
```

一期实际公网服务使用 venv，不依赖 Docker。GitHub Actions 曾完成镜像构建与容器健康 smoke，但没有推送镜像仓库，因此不能假定存在可 `docker pull` 的官方项目镜像。原 workflow 已随归档迁移，不再自动执行。

## 下次部署应沿用的检查

固定代码 commit 和运行配置，构建同一份 wheel/镜像；上传后检查模块版本与安装位置，使用单实例可写数据目录。先验证健康、错误鉴权、Add 后 Search、同 ID 重放和用户隔离，再小规模验证真实 provider 的完成状态与费用。升级之前留回滚制品，但备份不能超出数据保留期限。

停止评测后的收尾要涵盖 API、后台任务、自动重启、续期、数据库副本和部署密钥。服务器实例仍保留时，ECS 本身的费用不会因关闭 API 自动停止；本次没有释放实例或改变云账号资源。
