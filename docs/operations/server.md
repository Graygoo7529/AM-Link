# 服务器接入经验

2026-09-23 已停止一期 API、删除一期数据/代码/专用证书，并将服务器改为与 AM-Link 无关的通用公网基础设施。当前长期示例为 `http://121.43.49.84/hello` 和 `http://121.43.49.84/health`；一期旧地址不再调用。

## 一期部署链路

```text
本地源码 -> 构建 wheel -> SSH/SCP 上传 -> 服务器 venv 安装
公网 HTTP :80 -> Nginx -> 静态 hello 示例；未来域名 HTTPS :443 -> Nginx -> 独立 loopback 服务
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

一期曾使用测试 IP 证书做链路验证。2026-09-23 的生产申请使用了普通域名式参数，因此 Certbot 将裸 IP 当作不支持的标识而拒绝；这不是当前 CA 的完整能力边界。Let’s Encrypt 已于 2026-01 开放公网 IP 证书，要求 `shortlived` profile，约 160 小时有效；服务器 Certbot 5.7.0 已具备对应参数。当前通用示例仍只提供 HTTP，因为没有申请或配置任何证书。

### 当前可选证书路径

1. **域名 + Let’s Encrypt（推荐）**：准备一个解析到本机的域名，Nginx 80 保留 `/.well-known/acme-challenge/`，执行 `certbot certonly --webroot -w /var/www/certbot -d <domain>`；也可以用 DNS-01 验证。Nginx 443 加载 `fullchain.pem` 和 `privkey.pem`，`public-certbot-renew.timer` 定期执行 `renew --quiet`，deploy hook 只 reload Nginx。域名证书更适合长期服务和官方评测。
2. **裸 IP + Let’s Encrypt shortlived**：先用 staging 验证，再去掉 `--staging` 申请生产证书：

   ```bash
   /opt/certbot/bin/certbot certonly --staging \
     --preferred-profile shortlived \
     --webroot -w /var/www/certbot \
     --ip-address 121.43.49.84
   ```

   生产申请时删除 `--staging`，并配置 Nginx 443 使用 `/etc/letsencrypt/live/121.43.49.84/` 下的证书。IP 证书只能短期有效，必须确认 `certbot renew`、deploy hook、Nginx reload 和到期前告警全部可用；HTTP-01 或 TLS-ALPN-01 可用于验证，DNS-01 不适用于 IP。Certbot 的 Nginx 安装插件目前不负责 IP 证书安装，需要手工写 443 配置。
3. **商业 CA 的 IP 证书**：阿里云文档说明，正式证书中只有部分品牌的 OV 单 IP 证书支持公网 IP（如 GlobalSign、GeoTrust、vTrus、CFCA）；个人测试证书不支持公网 IP。Sectigo 也支持通过 HTTP/HTTPS CSR hash 完成 IP 控制验证。此路径通常付费，签发和续期更多依赖供应商流程，适合必须保持较长单证书有效期的场景。
4. **自签名或私有 CA**：只适合内部服务，浏览器和主办方通常不信任，不能用于公网参赛接口。

签发后必须用 `openssl s_client` 或 `curl` 检查 SAN、有效期、证书链和实际 443 链路；证书私钥只留在服务器 `/etc/letsencrypt` 或 CA 指定目录，不能交给官方或写入 Memory System Key 申请。

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

当前通用基础设施：`nginx.service` 已启用并监听 80；`public-certbot-renew.timer` 已启用，每 6 小时触发一次，当前无证书时命令正常退出。`/opt/public-web/README.md` 是服务器上的可读维护说明；`/var/www/public/hello.json` 是示例内容。新增应用必须使用独立用户、loopback 端口和独立 Nginx location/server。ECS 实例仍保留，云资源费用与 API 是否运行是两件事。

## 官方接口凭据

提交时只给官方：Add URL、Search URL、健康检查 URL、认证方案和 Memory System Key。Eval/Leaderboard Key 是官方签发的评测平台凭据，不放进服务器环境，也不用于 Add/Search。URL 不包含用户名、密码或 Key；公网地址应先通过健康、鉴权、Add 后 Search、重复 Add 和隔离检查。官方要求 HTTPS 生产接口，并拒绝解析到私网、回环或链路本地地址的 URL。
