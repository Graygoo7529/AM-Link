# 服务器接入经验

2026-09-23 已停止一期 API、删除一期数据/代码/专用证书，并将服务器改为与 AM-Link 无关的通用公网基础设施。当前示例为 `https://121.43.49.84/hello` 和 `https://121.43.49.84/health`，HTTP 也可访问；旧 Add/Search 返回 404。

## 一期部署链路

```text
本地源码 -> 构建 wheel -> SSH/SCP 上传 -> 服务器 venv 安装
一期公网 HTTPS :443 -> Nginx -> 127.0.0.1:8080 Uvicorn -> SQLite + 外部模型
```

服务器是阿里云 ECS，IP `121.43.49.84`。通过系统 OpenSSH 的 `ssh` 和 `scp` 对接；登录资料在本地 `docs/private/server-access.md`。本地无交互会话曾用临时 SSH_ASKPASS 脚本提供已授权密码，操作后删除脚本；复杂远程命令先写成 LF 换行脚本再上传，避免 PowerShell 与 Bash 双重展开。服务器账号不写入公开仓库，服务进程不使用 root。

### 一期历史部署

应用使用独立 `aml` 用户、单个 Uvicorn worker 和 systemd 托管；SSH 管理用户与应用运行用户不同。以下路径只描述一期历史部署，当前服务器不再保留这些 AM-Link 资源：

| 路径/服务 | 用途 |
| --- | --- |
| `/opt/aml-memory/app`、`/opt/aml-memory/venv` | 工作目录和应用依赖 |
| `/etc/aml-memory.env` | systemd 注入的环境配置，权限 600 |
| `/var/lib/aml-memory` | SQLite、WAL、Markdown 派生记忆及旧备份 |
| `aml-memory.service` | 启动、故障重启及应用权限约束 |
| Nginx 80/443 | HTTP 跳转 HTTPS、TLS 终止、转发 loopback API |

Nginx 原配置为请求体 4 MiB、连接超时 10 秒、收发超时 180 秒。它们是一期部署取值，不是二期标准；尤其不能直接用来承接二期多模态请求。服务器安全组与本机监听都必须检查；应用 8080 保持 loopback 即可。

## 当前 IP HTTPS 与续期

已按用户选择实施 **裸 IP + Let’s Encrypt shortlived**。Nginx 提供 80/443 静态示例与 HTTP-01 challenge；Certbot 负责向 CA 申请和续期，Nginx 负责加载证书及 TLS。此前“裸 IP 不支持证书”的结论错误，一次命令失败不能代表 CA 不支持；一期也使用了 IP HTTPS。

生产证书名为 `public-ip`，路径 `/etc/letsencrypt/live/public-ip/{fullchain,privkey}.pem`；续期配置 `/etc/letsencrypt/renewal/public-ip.conf` 保存了生产 ACME 地址、`required_profile = shortlived` 和 webroot。申请方式为：

```bash
/opt/certbot/bin/certbot certonly \
  --server https://acme-v02.api.letsencrypt.org/directory \
  --cert-name public-ip --required-profile shortlived \
  --webroot -w /var/www/certbot --ip-address 121.43.49.84
```

日常由 `public-certbot-renew.timer` 每 6 小时触发续期检查；不需要重复签发或强制续期。续期服务最多运行 5 分钟，关闭 Certbot 的额外随机等待；deploy hook 先 `nginx -t` 再 reload。随后检查磁盘证书剩余时间至少 48 小时，失败会标记 systemd 服务失败并写 journal，**尚未配置外部邮件/消息告警**。保持公网 80 的 challenge 路径可达，IP 证书不能使用 DNS-01。

```bash
systemctl list-timers --all public-certbot-renew.timer
journalctl -u public-certbot-renew.service -n 30 --no-pager
openssl x509 -in /etc/letsencrypt/live/public-ip/cert.pem -noout -dates -ext subjectAltName
/opt/certbot/bin/certbot renew --cert-name public-ip --dry-run \
  --run-deploy-hooks --no-random-sleep-on-renew \
  --deploy-hook /usr/local/sbin/public-certbot-deploy-hook
curl --fail https://121.43.49.84/hello
```

2026-09-23 验收：独立 staging 签发、生产签发、IP SAN/公开信任链、Nginx 配置测试、公网 HTTPS hello/health、续期 dry-run 与 deploy hook 全部通过，未跳过 TLS 校验；旧 Add/Search 均为 404。首张新证书发行者为 Let’s Encrypt YE1，北京时间到期 **2026-09-30 08:53:10**；每张约 160 小时，长期可用依靠持续续期，实际到期时间以当前证书为准。staging 首次临时 503，按 Retry-After 后一次重试成功，没有新增后台重试机制。

Nginx 配置在 `/etc/nginx/sites-available/public-web`；变更前配置备份在 `/opt/public-web/backups/pre-https/`。staging 测试目录已清理。私钥只留服务器，不能给官方或写入仓库。未来也可以申请域名证书或商业 IP 证书；自签名不能替代公开可信证书。参考：[Let’s Encrypt IP 证书](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)、[Certbot 获取方法](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

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

当前通用基础设施：`nginx.service` 和 `public-certbot-renew.timer` 已启用自启动，公网监听 22/80/443。`/opt/public-web/README.md` 是服务器上的可读维护说明；`/var/www/public/hello.json` 是示例内容。新增应用必须使用独立用户、loopback 端口和独立 Nginx location/server。ECS 实例仍保留，云资源费用与 API 是否运行是两件事。

## 官方接口凭据

提交时只给官方：Add URL、Search URL、健康检查 URL、认证方案和 Memory System Key。Eval/Leaderboard Key 是官方签发的评测平台凭据，不放进服务器环境，也不用于 Add/Search。URL 不包含用户名、密码或 Key；公网地址应先通过健康、鉴权、Add 后 Search、重复 Add 和隔离检查。官方要求 HTTPS 生产接口，并拒绝解析到私网、回环或链路本地地址的 URL。
