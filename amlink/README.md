# AM-Link 0.3.2-continuation

当前方法见[根设计](../DESIGN.md)。模型默认且必须使用 gpt-4o-mini、text-embedding-v4/1024维。

## 运行

```powershell
.\.venv\Scripts\python.exe -m amlink --env-file docs/private/amlink.env --host 127.0.0.1 --port 8080
```

进程读取 AML3_*，示例见 [.env.example](.env.example)。只有显式 load_env_file / --env-file 才转换旧私有文件的受支持 AML2 字段，不读取环境残留的 AML2 变量。两类凭据缺失时拒绝启动。当前为单worker，数据库owner防止多进程覆盖。同用户串行，不同用户可线程并发。

默认新库 amlink/data/memory.sqlite3，SQLite版本301、索引指纹passages-v2，不迁移旧库／旧向量。私有文件若另设路径则以该路径为准。HTTP入口：
- GET /health：进程健康，不代替外部模型可用性探测。
- POST /v1/memory/add：request_id/messages/user_id/session_id；消息保留role/content/timestamp。
- POST /v1/memory/search：query/user_id/top_k，可选options；返回有序data。
- 鉴权支持bearer/token/x-api-key；none仅供本机开发。正式暴露服务前应设置鉴权。

## 实现边界

engine.py 编排；reading.py 负责原文锚点、单位、邻接与确定性装箱；store.py 只负责原子存储；providers.py 单次模型调用；tool_contract.py 校验当次工具；observation.py 对接靶场；native.py 是本地实验入口。

必要embedding在接收前完成。成功Add后，整理最多两小批，失败批不重试；原文继续可检索。Search不读WorkingMemory，不运行Reflection。派生note只做检索入口，交付必回到精确原文。

配置默认：16段/12000字符整理批；至少2个Add积累（会话边界例外）；每批最多6条400字符笔记。模型操作引用只有本次局部编号，稳定ID/偏移/入库序号放入观测账本；自然标题、原文、角色和说话日期仍可见。

Search首先展开24个命中入口，含邻接/来源反链最多48个episode；首轮50,000字符正文＋最多24项/8,000字符未读目录。约600字符连续原文块合并相邻短段，保留内部换行和标题边界。Select输出positions、最多2条queries、4个read_more；选中未读预览会先展开完整原文，经过最终Select才可交付。补查/补读优先新增，已见未选范围不重复铺开，无增量不再Select。末轮58,000字符，最多两次Select；交付24,000字符。最终自然先后说明和原文在预算内，来源范围保留在观测中。累计provider预算默认0表示不按进程寿命限流；实验runner显式设置每库预算。每次调用/请求仍受90秒/1740秒期限约束。

遗忘确认阶段跨Add/重启保存，下一条普通用户消息结束；助手复述已撤销陈述的范围不进入索引，无关句段保留。这不改变历史遗忘仍按整条来源屏蔽的局限。必要判断失败时本次接收原子撤销。

词法实现是对存储词项计算BM25，不是SQLite FTS。向量是本用户范围内精确扫描，并非ANN。来源反链可补充同一note引用的其它原文，不推断自由语义关系。

## 验证和实验

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m research.benchmark.broad prepare --output research/benchmark/data/plans/my-suite
.\.venv\Scripts\python.exe -m research.benchmark.broad run --plan research/benchmark/data/plans/my-suite/suite.json --indices 0 --prefix my-run --env-file docs/private/amlink.env
```

prepare只冻结数据/源码，不调用模型。run会真实收费调用，每次新库，禁止源文件改变后拼接结果。所有运行、原文、模型输入输出与数据库只保存在忽略的data目录。归档代码不应作为测试发现路径。

本地回归证明契约，不证明语义质量。本版153回归＋5子测试通过；六类18完整历史555/555 Add、61/61 Search/Answer、604/606整理，仍有Select漏选等质量问题。见[实施核对](../docs/doing/2026-10-30-reading-continuation-implementation.md)和[执行计划](../docs/phase-3/2026-10-30-reading-continuation-execution.md)。旧reading公开r2的400/400 Add、36/38 Search、409/420整理保留为旧版结果，不能混入本版或将HTTP成功当准确率。
