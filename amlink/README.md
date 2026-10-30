# AM-Link 0.3.0-clean

当前方法见[根设计](../DESIGN.md)。模型默认且必须使用 gpt-4o-mini、text-embedding-v4/1024维。

## 运行

```powershell
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

进程读取 AML3_*，示例见 [.env.example](.env.example)。只有显式 load_env_file / --env-file 才转换旧私有文件的受支持 AML2 字段，不读取环境残留的 AML2 变量。两类凭据缺失时拒绝启动。当前为单worker，数据库owner防止多进程覆盖。同用户串行，不同用户可线程并发。

默认新库 amlink/data/memory.sqlite3，SQLite版本300，不迁移二期数据。私有文件若另设路径则以该路径为准。HTTP入口：
- GET /health：进程健康，不代替外部模型可用性探测。
- POST /v1/memory/add：request_id/messages/user_id/session_id；消息保留role/content/timestamp。
- POST /v1/memory/search：query/user_id/top_k，可选options；返回有序data。
- 鉴权支持bearer/token/x-api-key；none仅供本机开发。正式暴露服务前应设置鉴权。

## 实现边界

engine.py 编排；store.py 只负责原子存储；providers.py 单次模型调用；tool_contract.py 校验当次工具；observation.py 对接靶场；native.py 是本地实验入口。

必要embedding在接收前完成。成功Add后，整理最多两小批，失败批不重试；原文继续可检索。Search不读WorkingMemory，不运行Reflection。派生note只做检索入口，交付必回到精确原文。

配置默认：16段/12000字符整理批；至少2个Add积累（会话边界例外）；每批最多6条400字符笔记；24候选；24000字符输出；最多两次Select。累计provider预算默认0表示不按进程寿命限流；实验runner显式设置每库预算。每次调用/请求仍受90秒/1740秒期限约束。

词法实现是对存储词项计算BM25，不是SQLite FTS。向量是本用户范围内精确扫描，并非ANN。来源反链可补充同一note引用的其它原文，不推断自由语义关系。

## 验证和实验

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m benchmark.broad prepare --output benchmark/data/plans/my-suite
.\.venv\Scripts\python.exe -m benchmark.broad run --plan benchmark/data/plans/my-suite/suite.json --indices 0 --prefix my-run --env-file docs/private/amlink.env
```

prepare只冻结数据/源码，不调用模型。run会真实收费调用，每次新库，禁止源文件改变后拼接结果。所有运行、原文、模型输入输出与数据库只保存在忽略的data目录。归档代码不应作为测试发现路径。

本地回归证明契约，不证明语义质量。最新实验以[实施报告](../docs/doing/2026-10-29-clean-rebuild-implementation.md)为准。
