# 0.3.4-continuity 服务器部署记录

用户已明确要求部署。部署对象为一期保存的服务器121.43.49.84，使用本地私有访问资料；模型和接口密钥不进入本记录。2026-10-31重新读取AGENTS、一期部署记录与当前官网。

## 固定内容与边界

- 生产提交：`1f9136563bdc3d56d0425d57000739adb8dc0379`，版本`0.3.4-continuity`，DB301/passages-v2。
- 从该干净提交重新生成的包：`amlink/data/releases/1f91365/amlink-0.3.4-continuity.tar.gz`，SHA256 `1bea272338b0b5a3d8da0701ceb7fac189c1091c9cf06049157da6b900665114`。与此前未提交包区分；方法源文件沿用已验证版本。
- 目标Textual，仅Add/Search。mini、v4/1024固定；没有内部重试或Search内Answer。
- 一期经验保留：独立服务用户、单进程SQLite、持久盘、鉴权、可信HTTPS、自动证书续期、固定版本及重启验证。不沿用一期重试/后台补偿或旧模型。
- 不恢复旧实验库；官方数据不写入本地研究室，不记录请求正文或完整模型I/O。不申请官方评测、不消耗官方smoke/full名额。

## 执行顺序

1. 已只读核验：Ubuntu24.04、2核、约1.6GiB内存、2GiB swap、约34.7GB可用磁盘；无现存AM-Link服务/数据库。Nginx运行着独立public-web网站，必须保留原有路由。
2. 当前IP证书由Let's Encrypt签发，覆盖121.43.49.84；有效至11月4日08:18:42 UTC。`public-certbot-renew.timer`运行，复用既有webroot与续期链，不新建重复定时任务。
3. 安装隔离Python3.13.14及锁定依赖；验证发布包、依赖与服务用户权限，不升级系统Python。
4. 独立数据目录`/var/lib/amlink`、配置`/etc/amlink/amlink.env`；生成本期接口密钥，模型凭据使用现有本地配置，经SSH传输。
5. systemd单进程监听127.0.0.1:8080；先完成服务器内部合成smoke，再将`/amlink/`代理到应用。保留原`/hello`、`/health`和ACME路径，新增代理采用1800秒期限与禁止上游重发。
6. 外部验证HTTPS证书、鉴权、真实Add/Search、并发幂等、隔离和重启持久性；最后核对运行进程、配置、源码身份和数据库。
7. 保存不含凭据的部署结果、参评接口清单和回退说明。尚未执行的检查不能写成通过。

## 官方核对

[接入指南](https://agentmemoryleaderboard.ai/api-guide)要求固定自托管接口、同步Add成功即持久化可检索、user_id隔离、top_k上限和调用方重试；Health不鉴权。URL路径可由参赛方配置，因此本次使用独立`/amlink/`前缀。

[赛事说明](https://agentmemoryleaderboard.ai/competition/)确认学术榜模型组合与材料截止，且二期评测结束后不要求持续公开接口；一期“持续开放30天”不是当前规则。评测数据及派生副本仍按官方数据条款在任务完成后30天内处理。

## 执行结果

部署与公网自检已完成。生产代码未改，固定提交为`1f91365`；本地仅新增部署记录和更新文档入口，没有自动提交或申请官方评测。

### 可用于提交的接口

| 用途 | 地址 |
| --- | --- |
| Add（POST） | `https://121.43.49.84/amlink/v1/memory/add` |
| Search（POST） | `https://121.43.49.84/amlink/v1/memory/search` |
| Health（GET，无鉴权） | `https://121.43.49.84/amlink/health` |

鉴权为`Authorization: Bearer <MemorySystemKey>`。本期新生成的接口密钥保存在忽略的`docs/private/amlink-server.env`的`AML3_API_KEY`；该文件还包含模型凭据，不应整份提交给赛事方。官方仅需接口密钥，不需模型服务的密钥。服务器对应配置为`/etc/amlink/amlink.env`，权限0640、root:amlink。新密钥不复用一期值。

便于填写表单的独立私有清单为`docs/private/amlink-submission.md`，其中仅含接口密钥、接口地址和版本信息，没有模型服务商凭据。

### 已完成的核对

| 检查 | 实际结果 |
| --- | --- |
| 发布身份 | 包SHA256、21个清单文件哈希、干净提交身份一致 |
| Linux环境 | 隔离Python3.13.14，21项适用依赖严格匹配锁定版本；依赖兼容检查通过，系统Python未改 |
| 内部HTTP与公网HTTPS | 两套合成smoke均通过；真实mini/v4调用，更新值可检索、无鉴权401、非法参数422、用户隔离 |
| 幂等 | 每套4个并发相同Add得到相同成功凭据；同request_id换内容被422拒绝 |
| 16路Add并发 | 16个不同用户、每人两批8条消息；32/32成功，第一批最慢1.364秒，第二批含整理最慢19.565秒 |
| Reflection | 16/16批完成、256条工作记忆已整理、生成95条note；只说明本次合成检查的结构合法完成 |
| 16路Search并发 | 16/16成功，最慢9.274秒，全部返回各自更新后的正确配额原文；没有执行Answer |
| 持久性 | 空闲时重启服务，公网读取同一用户仍成功；SQLite完整性检查ok，DB301，36个逻辑Add凭据仍在 |
| 运行与权限 | amlink已启用开机启动，active/running；进程仅监听127.0.0.1:8080；数据目录0700、库0600；无自动崩溃重启 |
| TLS与原站 | 系统信任链验证通过，IP SAN匹配；AM-Link的HTTP请求308转HTTPS，原/hello与/health响应哈希未改变 |
| 证书续期 | 既有6小时定时器active，最近13:20执行成功、下一次19:20；续期成功后检查并reload nginx，另检查至少48小时有效期；本轮未强制续签 |

上述两次smoke、并发检查与重启核验均无请求或模型失败重试。当前库只含18个独立的`deployment31-*`合成用户、260条原文/episode、95条note、36条成功凭据；未恢复旧实验库，官方用户命名空间未被使用。4条小smoke原文仍在pending，但可直接Search，符合Add契约。

并发期间进程组内存峰值89,874,432字节（约85.7MiB）；机器约1.6GiB内存、2GiB swap。该负载只验证短合成历史的连通、并发及整理，不代表长历史容量或官方全量合格率。生产未启用研究I/O记录器，本轮不报告无法精确核对的模型tokens或调用总数。

官网[机器契约](https://agentmemoryleaderboard.ai/api/v1/evaluation-tracks/textual/contract)在本次读取时规定`max_add_concurrency`为16–64，`search_concurrency`为16–256；旧部署文档的4/1建议已更正。初次官方验证应选最低16/16，后续容量只依据实际运行调整。官方Smoke/Full均未发起。

本地无凭据证据保存在忽略的`amlink/data/deployment31/`：`official-contract.json`、`concurrency-result.json`、`public-before.json`、`public-final.json`及本轮部署脚本。服务器安装资料与原站配置备份在`/root/amlink-deploy-20261031/`。

### 维护与回退

服务为`amlink.service`，代码目录`/opt/amlink/current`，运行环境`/opt/amlink/venv`，持久库`/var/lib/amlink/memory.sqlite3`。网关读写期限1800秒，方法期限1740秒，单模型期限90秒；nginx明确禁止上游重发。证书仍由`public-certbot-renew.timer`维护，AM-Link不另建证书定时器。

正式评测中不主动重启或更新版本。若需撤销本次部署，先停止amlink，再移除public-web里的`include /etc/nginx/snippets/amlink.conf;`，`nginx -t`通过后reload；不要直接覆盖未来可能已变化的整个站点配置。原站部署前备份为`/root/amlink-deploy-20261031/public-web.before`。数据库和私有配置保留，不随代码回退删除；备份使用SQLite backup API或停机后完整复制，不能只复制活动WAL库的主文件。

截至本轮，官方提交与运行未开始，因此没有官方数据清理截止日。实际任务完成后依官网条款记录数据及派生副本的30天处理期限。当前部署检查不代替官方Smoke或Full，也不改变之前的语义质量结论。
