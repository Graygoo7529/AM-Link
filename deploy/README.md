# 部署 AM-Link 0.3.4-continuity

本目录固定当前文本记忆方法的运行方式。对外只有 Add/Search，模型为 `gpt-4o-mini`、`text-embedding-v4/1024`；不包含研究 Answer、数据集和案例库。源码包不是服务器部署，也不是官方 smoke 通过证明。

2026-10-31已将固定提交`1f91365`实际部署到`https://121.43.49.84/amlink/`。Linux锁定依赖、真实模型、16路并发合成检查、HTTPS与重启持久性均通过；详见[部署记录与接口清单](../docs/doing/2026-10-31-server-deployment.md)。尚未运行官方Smoke/Full。

## 发布内容和核验

在项目根目录执行 `python deploy/package.py`，输出到忽略的 `amlink/data/releases/`。压缩包只包含明确列出的生产模块、设计文档、本目录的运行文件和依赖锁定表。`manifest.json` 为每个文件记录 SHA256，同时记录基线 commit 和工作区是否有未提交修改；不能把基线 commit 当作未提交包的源码身份。包外 `.sha256` 核对整个压缩包。

部署前由作者提交当前修改并固定参评 commit；如果重新打包，请使用新的输出目录，不覆盖已审阅包。不要上传整个工作目录或旧实验数据库。

已核验本机Windows/Python3.13和服务器Ubuntu24.04/Python3.13.14；服务器严格安装锁定依赖并通过包核验，本机依赖未升级。本机无Docker环境，没有验证容器。

## Linux 单进程部署

需要Python3.13、可持久化本地磁盘、可信TLS域名或IP证书、至模型服务的网络和有效额度。当前方法按用户扫描词法/向量，不声明已通过官方full规模压测。本次读取的[官方机器契约](https://agentmemoryleaderboard.ai/api/v1/evaluation-tracks/textual/contract)规定Add并发16–64、Search并发16–256；初次官方验证选择最低16/16，短合成负载已通过此并发。服务只有一个worker；不要运行多个进程争用同一SQLite库，不使用reload。

约定目录：

- `/opt/amlink/releases/amlink-0.3.4-continuity/`：本次解压代码；`/opt/amlink/current` 指向它。
- `/opt/amlink/venv/`：专用 Python 环境。
- `/etc/amlink/amlink.env`：独立配置和凭据，只有 root 与服务用户可读。
- `/var/lib/amlink/memory.sqlite3`：新建的空数据库，服务用户可写；不放在发布代码目录。

以下命令为新主机安装示意。本机对应服务器已经安装，不要重复执行创建、初始化或覆盖配置步骤。实际使用uv安装隔离Python3.13.14与专用环境，详见部署记录；升级时先停止旧服务并备份数据库，不覆盖运行中的数据库。

```sh
# 创建服务用户与目录（已存在则核对并复用）
sudo useradd --system --home /var/lib/amlink --shell /usr/sbin/nologin amlink
sudo install -d -m 0755 /opt/amlink/releases
sudo install -d -m 0750 -o root -g amlink /etc/amlink
sudo install -d -m 0700 -o amlink -g amlink /var/lib/amlink

# 在上传包所在目录校验、解压；检查文件内容后再建立 current 链接
sha256sum -c amlink-0.3.4-continuity.tar.gz.sha256
sudo tar -xzf amlink-0.3.4-continuity.tar.gz -C /opt/amlink/releases
sudo ln -s /opt/amlink/releases/amlink-0.3.4-continuity /opt/amlink/current
sudo python3.13 -m venv /opt/amlink/venv
sudo /opt/amlink/venv/bin/python -m pip install -r /opt/amlink/current/deploy/requirements.lock
/opt/amlink/venv/bin/python /opt/amlink/current/deploy/verify.py

sudo install -m 0640 -o root -g amlink /opt/amlink/current/deploy/.env.example /etc/amlink/amlink.env
# 用编辑器在服务器内填写模型凭据和新生成的 Memory System Key；不要放入命令行参数。
sudoedit /etc/amlink/amlink.env
sudo install -m 0644 /opt/amlink/current/deploy/amlink.service /etc/systemd/system/amlink.service
sudo systemctl daemon-reload
sudo systemctl enable --now amlink
curl --fail http://127.0.0.1:8080/health
```

`verify.py` 检查包内哈希、Python 与依赖版本。安装成功不等于包验证通过，验证通过不等于模型可用。鉴权示例默认 Bearer，模型密钥和接口密钥必须填写；缺少必要配置时服务拒绝启动。不要把研究配置中的累计调用预算带入长期服务。

将 `nginx-location.conf` 放到实际域名的 HTTPS server 内，配置证书后先执行 `nginx -t`，再加载。应用仅监听回环地址，外部访问由 HTTPS 代理接入。代理不重发失败请求，读写超时1800秒；方法内部期限1740秒，单次模型期限90秒。服务重启策略是进程崩溃恢复，不是请求或模型重试。网关显式32MiB请求上限只适用于本版文本接入，不能据此申报多模态支持。

现有服务器复用public-web站点的IP证书，独立`/amlink/`前缀剥除后转发到应用；仅该前缀的HTTP请求转到HTTPS。原`/health`属于原站，AM-Link健康地址必须填写`/amlink/health`。现网配置是`/etc/nginx/snippets/amlink.conf`；发布包内通用示例与这个站点前缀不同。

## 本机与服务器 smoke

下面的工具发送人工合成材料，会产生少量真实模型调用；为合成用户新建记忆，不读取官方数据。它检查无鉴权健康、401、422、4份并发相同 Add 的成功凭据、相同 request_id 换内容拒绝、立即 Search、更新原文可见和用户隔离。任何一步失败直接结束，没有内部重试。

```sh
sudo -u amlink /opt/amlink/venv/bin/python /opt/amlink/current/deploy/smoke.py \
  --base-url https://YOUR_DOMAIN --env-file /etc/amlink/amlink.env \
  --user-id deployment-smoke-REPLACE_WITH_UNIQUE_ID

# 在空闲时重启服务，核对同一合成用户仍可检索；正式评测中不主动重启。
sudo systemctl restart amlink
sudo -u amlink /opt/amlink/venv/bin/python /opt/amlink/current/deploy/smoke.py \
  --base-url https://YOUR_DOMAIN --env-file /etc/amlink/amlink.env \
  --user-id deployment-smoke-REPLACE_WITH_UNIQUE_ID --verify-only
```

这不是官方 smoke。申请材料需填写固定版本、Add `/v1/memory/add`、Search `/v1/memory/search`、Health `/health`、鉴权方案和容量限制；由用户提交申请并发起官方 smoke 后，才能准备 full。

## 运行语义与维护

Add 200 表示原文、episode、索引与成功凭据已提交；缓冲尾部可立即检索。满足批次门槛时，同次 Add 会等待有界整理结束，整理失败仍保留可检索原文；失败不会在下一次 Add 自动重试。接收前必要操作失败不留半写入，调用方可用相同 request_id 重送。Search只读已提交记忆，返回证据；两轮 Select 上限，工具失败明确返回错误。模型和HTTP调用均不做内部错误重试。

服务不接入研究观测记录器，不记录请求正文或模型I/O。常规 HTTP 日志、状态码和服务异常用于运维；详细研究应继续使用公开数据的新库。DB301/passages-v2 与旧库不兼容，启动会检查模型/索引指纹。不要把旧库作为新空库复制。

备份应在停止服务后复制完整数据库，或使用 SQLite backup API；不要只复制正在写入的主文件而遗漏 WAL。回退代码前核对数据库版本和索引指纹，不能靠删除数据库消除启动错误。评测数据生命周期按官方规则处理；公开研究档案与官方评测库分开。

2026-10-31复核的[官方接入指南](https://agentmemoryleaderboard.ai/api-guide)要求自托管、固定版本、同步可检索和样本隔离。当前仅准备文本赛道；不包含图片输入支持。官方页面列明材料截止为10月31日23:59（UTC+8），评测于11月4日23:59停止；以实际提交时官网为准。
