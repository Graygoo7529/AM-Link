# 项目记忆

## 当前状态（2026-10-30）

- 当前方法是第三版 `amlink/ 0.3.0-clean`，数据库版本300。先读根README、`docs/README.md`、根`DESIGN.md`、`docs/phase-3/2026-10-29-clean-rebuild-plan.md`和`docs/doing/2026-10-29-clean-rebuild-implementation.md`。赛事背景另读`docs/phase-2/integration-research.md`，注意其核验日期。
- 用户因二期r11只有26/75个Reflection组完成，明确要求归档、清理实验数据并从头重构。旧源码、测试、设计及台账在`archive/phase-2/20261029-clean-rebuild/`。当前Git基线60438c3；归档包含此前未提交改动。旧项目长记忆见归档AGENTS-r11.md，中途AGENTS-transition.md不是当前事实。
- 第三版：不可变Source及保真episode；必要BM25词项/v4向量索引后原子接收；跨Add积累，最多两小批单次Reflection生成note导航；只新增来源链接，不修改旧事实、不生成语义关系边、不运行审查修订loop。失败批unorganized，不内部重试，原文仍可检索。
- Search每次独立，只读已索引记忆；BM25+向量→来源披露/反链/邻接→LLM Select→最多两条具体缺口Query→必要时单字段最终Select；返回原文卡，保持选择顺序，不输出生成摘要作为事实。不读WorkingMemory、不做Reflection/Answer。
- 向量与Select必用，没有失败时纯词法降级、默认关闭的图或隐藏备用分支。模型固定gpt-4o-mini、text-embedding-v4/1024维、embedding每批最多10。切段保守控制UTF-8字节，不把字符数宣称为真实token测量。
- 最新实测/成本/工程验收以实施报告为准。r1/r2协议版本不能拼接成同版成绩；100题清单只是准备，未运行题目不能算通过。早期无provider的clean-smoke-native-r3已退出活动登记，不作为当前方法验证。
- 旧benchmark原始实验数据库/轨迹/计划/研究环境和旧本地可视化数据已按授权清理，不能承诺恢复；原始数据集、prepared包、案例文档与历史报告保留。少量旧pytest ACL拒绝访问缓存仍在归档，不是活动实验。新实验只用新库。默认库已新建为空、health200，仅说明本机初始化成功。
- 主题遗忘采用直接指令入口、候选逐条独立核对、整消息屏蔽，存在误删/漏删和成本风险；note存在同义重复/错误归属风险；有限候选和两轮检索不保证长链完整。不要把整理协议完成、API成功当作语义质量通过，更不能声称已可正式参赛。

- 本轮最终113回归+3子测试。18观测档案748调用/748响应（mini305/v4 443），输入1,157,219/输出38,319tokens；开发成本盘点135/139 Add、46/50 Search，不是同版成绩。最终r3 PersonaMem 13/13 Add、6/6 Search、14/14批，135调用/199,571输入tokens；177活动来源全有episode，5屏蔽、6指令。已知两类误删修正，但同义漏删与整消息连带屏蔽未验收。r1 LoCoMo 31/31批、来源7/21；PerLTQA5/5批、4/4来源；r2 BEAM46/46批。版本不能混成同版通过。最终100题清单clean30-100-r3只完成6题/13 Add，94题/767 Add未运行。

## 项目与工作规则

- AM-Link是Graygoo7529的原创Agent Memory Leaderboard记忆系统，只提供Add/Search；官方负责Answer/Eval。TinySoul-Agent是同作者原创参考，位于忽略的reference目录。
- 一期0.3.0代码在archive/phase-1，Smoke/Full历史已完成；一期部署、专用数据库和证书已清理。当前没有新部署或官方Smoke/Full。保留一期历史，不在其中写新方法。
- `DESIGN.md`记录当前方法；修改方法同步更新计划/报告，区分已实现、真实验证与未验证。历史phase-2/doing文件保留引用，不将其“当前状态”视作今日事实。
- `casestudies/`留在根，catalog为唯一案例来源。统一展示入口`visualization/README.md`；网页与会话片段同源，无需保存选择状态。原文与轨迹仅进入忽略的data路径。
- 私有配置在忽略的docs/private/amlink.env，用户允许读取Key用于已授权的公开数据实验；不得打印或写入报告/源码。通过load_env_file或--env-file显式加载，受支持AML2字段映射AML3；不要依赖旧ZHIPU环境绑定。不自行修改凭据或安装依赖。
- 无内部错误重试。必要接收未提交时失败；已提交后的整理不完备不能撤销成功；同请求重送返回持久凭据。标准Search所需模型失败明确报错，不伪装空结果。
- 运行和缓存只写忽略路径；Windows移动/删除前核验绝对路径属于工作区，使用原生文件操作。不要从旧库/备份起跑新实验。
- 未明确要求时不自动Git提交、部署、推送或发消息。保留用户改动；结束说明未提交范围，可给commit建议。
- Windows开发；Python使用`.venv/Scripts/python.exe -X utf8`。必要时Git以`-c safe.directory=B:/WorkSpace/AM-Link`调用，不改全局Git配置。测试默认写独立忽略目录，避免ACL旧缓存。
