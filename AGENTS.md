# 项目记忆

## 当前轮更新（2026-10-31）

本轮按 `docs/phase-3/2026-10-31-search-evidence-improvement-plan.md` 实施了 Search 证据闭合、Select 任务形状提示和 Reflection 同来源近似去重。当前 `amlink/` 版本为 `0.3.3-evidence-closure`；`context_closure` 优先在同一 episode 内、必要时从已披露的同会话即时前一 episode 为代词/短确认/承接句补原文单位，模型选择与程序闭合在观测中分开记录。Search/Add 对外契约、原子接收、无内部重试和默认模型配置不变。`.venv\\Scripts\\python.exe -m pytest amlink/tests -q -ra` 结果为 63 passed。

本轮真实公开验证见 `docs/doing/2026-10-31-evidence-closure-real-validation.md`：新运行 `closure31-r16-e1` 至 `closure31-r19-e1` 共 139/139 Add、4/4 Search，使用真实 `text-embedding-v4/1024` 与 `gpt-4o-mini`；本地诊断 Answer 使用 GPT-5.4。结果显示 r16 时间比较受益于闭合，但 r17/r18 证据召回仍为 0.2/0.4，r19 仍有规则与新实例适用范围混用；不能宣称整体准确率提升。研究页面离线构建验证为 11 datasets、41 cases、45 studies、105 runs、314 questions；历史运行和研究分母未改写。

## 最新全量复核（2026-10-31）

按 `docs/phase-3/2026-10-31-fresh100-current-method-plan.md` 建立 `fresh32-*` 独立空库，覆盖 26 份公开历史、780/780 Add、100/100 Search；历史观测和默认库保留，没有把旧数据混入本轮分母。真实 Add/Search 使用 `text-embedding-v4/1024` 与 `gpt-4o-mini`，本地 Answer 使用 GPT-5.4。首轮 Answer 99/100 成功，唯一失败是长棋局输出达到 8192 上限，改用 16000 上限独立补跑成功；因此唯一问题不属于 Add/Search。

本轮 Search 观测为 103 Query、140 Select、62 `read_more` 和 4 个补充 Query。99/100 个首轮 Select 输入有原文 `UNREAD preview`，但预览不是自动交付的完整内容；只有选择或 `read_more` 后才展开。40 个问题进入第二次 Select，40/40 的后续模型输入没有显式上一轮 query、覆盖槽、补读理由或连续账本；首轮平均 9.43 个单位，末轮 7.92 个，29/40 至少丢掉一个首轮单位。最终装箱返回 487 个 evidence groups，76 个因字符预算省略。按可比 target 统计，single-hop/events/profile/social relationship 为 1.0，temporal 为 0.875，multi-session 为 0.667，multi-hop 为 0.207，open-domain 为 0.143；这些是 Search evidence 指标，不是官方 Answer 成绩。

当前 Select 正文主要显示本轮 `[N]` 位置、自然标题/角色/时间和原文；稳定的 `memory:episode/...#start:end` ref 仍主要在观测映射，不直接作为跨轮模型可见引用。因此 `carry` 程序上连续、模型叙事上仍像重新编号的一批材料。

Reflection 806/810 成功，4 次 schema/source/note-limit 错误没有使 Add 失败，但说明长尾整理协议仍不稳定。完整分析见 `docs/doing/2026-10-31-fresh100-current-method-findings.md`。当前最明确的下一步是把已有观测和 `carry` 转成模型可读的检索连续性账本，并离线验证最终装箱的证据槽闭合；本轮尚未改变生产 Add/Search。

研究页面已重新构建并登记本轮：11 datasets、41 cases、45 studies、131 runs、414 questions；页面和运行工件都位于忽略的数据路径，未改历史分母。

## 当前状态（2026-10-30）

最新两组验证见`docs/doing/2026-10-30-intent-validation-findings.md`、同前缀ledger和`docs/phase-3/2026-10-30-intent-validation-plan.md`。基线941b34c；生产Add/Search/配置未改。用户明确批准智增增6200调用/6000万输入字符。96固定候选组件：基线22/24、短证据说明21/24、目录前移24/24、预算说明24/24合法；短说明可补头盔/否定状态，却仍漏完成报告、误把推荐缺口当缺新城市旧记录；长引文预算仍失效，不上线。最终r3四类6历史24题两臂新库，各168/168 Add、24/24 Search/Answer；整理164/165与165/165，note788→798。mini14→16正确，逐题审读19正确/3未达标/2不确定→18/4/2，不能称提升；48答案全读，8题次另查原文/模型轨迹。pet去年时间已读未选、besides瑜伽的Query仍困主题、电影续读成功却末轮丢所指问句、新实例沿用旧实例定性；研究新增r16-r19。最终可观测1535尝试1535响应（mini538/v4 949/GPT5.4 48），输入2762091/输出106795tokens、缓存172416；0网络失败。此前r2注入Provider记录器未绑定，3库主动中断，127已落盘Add响应另3接收已提交；无Search、模型精确用量未知，不能漏计。按原硬预算上界额外≤1500调用/1050万字符，全轮≤3035调用/21195755字符。r3仅修研究factory接线，实际I/O完整；所有活动来源有episode、48交付原文范围/预算通过。页面两批12运行、4案例/8深入研究与评注追加；不混中断/同题分母。不改方法、依赖、凭据、默认库，无重试/删除/部署/提交。下一方向是按任务提出检索表达、共同证据/代词上下文保持、适用范围，而不是增设充分性硬门槛或长审查loop。

最新只读机制复核见`docs/phase-3/2026-10-30-selection-mechanism-review.md`。用户已提交`2a2983d`，本轮未改方法/配置、未调用模型。重建原61题77次Select：比赛日志关键原文在首轮44/52/53/50已读，两条补查无增量、没有第二轮，纠正旧叙述；头盔120为目录局部65而非62；酒店用户偏好首轮9被排除，末轮只有助手套餐，不能全部归因Answer。整理已见旧347/1000里程note仍新增近似笔记，120其实已存；主要方向是同次Select的任务/证据作用说明、目录展开与集合预算、旧note引导导航增量。均为待验证设计，不恢复图/审查loop、不宣布新收益。分析在忽略`research/data/selection30-audit/`，文档/案例及追加评注同步更正；原I/O和冻结记录不覆盖。

AM-Link 是 Graygoo7529 参加 Agent Memory Leaderboard 的原创记忆系统；只提供 Add/Search，官方负责 Answer/Eval。TinySoul-Agent 同为作者原创参考项目。

当前 `amlink/` 为第三版 `0.3.3-evidence-closure`、DB301／passages-v2。不可变原文与episode双索引；跨Add小批缓冲；Reflection一次生成只引本批原文的短导航note，先限定旧note范围再检索背景并进行同来源近似去重。Search保留BM25/向量、来源反链与真实邻接；24个入口、最多48段原文；首轮50K正文＋最多24项/8K未读目录，末轮58K、交付24K。Select选择约600字符连续原文块，唯一局部编号；输入包含由问题推导的补集、比较/状态、多项和指代任务形状提示；选未读预览表示先展开后末轮Select，不能直接交付预览。最多两轮、2补查/4主动补读；已选范围携入、新材料优先，无增量停止；末轮前后对代词/短确认/承接句执行同episode证据闭合，必要时使用已披露的同会话即时前一episode。标题/角色/说话日期自然可读，稳定ref/顺序/范围以及 model_selected/context_closure 在独立观测账本。没有自由BFS或语义图边。内部固定v4/1024与mini，真实默认使用；不做内部错误重试。

**最新：续读方案已实施并核对。** 先读`docs/doing/2026-10-30-reading-continuation-implementation.md`、同前缀run-ledger及`docs/phase-3/2026-10-30-reading-continuation-execution.md`。153回归＋5子测试。两版56组件保留：r1整理14/16、Select10/12合法；r2明确预览选择为阅读请求及sources职责后16/16、12/12合法。冻结最终版本六类18完整历史555/555 Add、61/61 Search/Answer、604/606整理；原12历史38题＋额外6历史23题，不是外部盲测。2整理失败为schema/条数超限，原文不丢。16次新增续读/3次无增量停止、2补查真实执行；120已在预览仍未选择，API冲突、Sprint完成报告及比赛日志已读事实仍被漏选。评论24引文逐字且互不重复，答案本题完成，但末轮选104块/装箱丢59块，不能宣布集合预算有效。61答案人工40符合题意/9未达标/12不确定，25题另查原文或轨迹；mini辅助42/19，与旧mini成绩不可直接混比。所有4914活动来源有episode、无屏蔽来源活动支持；61交付原文范围与预算复核通过。全轮79档案（23新库＋56组件）3428尝试/3428响应，输入4226740/输出231639tokens、缓存3328，无网络失败；原始材料与脚本在忽略的`research/data/continuation30/`。单一页面11数据集/37案例/37研究/88运行261问题条目，含重复和失败；构建/身份/静态校验，无真实原文浏览器访问。凭据/依赖/默认库未变，无提交或部署。工程及本轮验证完成，整体语义质量仍未验收。下面的“最新”均为此前阶段。

**最新：自然叙事与研究Answer。** 先读`docs/doing/2026-10-30-narrative-and-answer-findings.md`及`docs/phase-3/2026-10-30-narrative-and-answer-plan.md`。用户允许提升本地Answer，已默认GPT-5.4 medium/120秒/8192completion tokens，保持完整Search内容、无gold、单次调用，无模型回退；campaign同步，Judge仍mini辅助。固定原r2六类12历史的36个成功Search＋其中12题交叉对照，合计60 Answer响应；不是新Add/Search成绩，两次旧Search失败仍失败。另57个mini组件与1次provider探测，全轮118尝试118响应，输入455993/输出46649tokens，缓存0，无网络失败；数据脚本完整I/O忽略存于`research/data/narrative30/`。147回归＋5子测试通过。Reflection出现本批1与全局17混用；精简后5/5合法仍把家人写成兄弟。Select精简视图新旧提示各12/12合法，但550单位评论仍机械选100/549；单位中位10字符、465不足100。新探索提示普遍补读且泛查，不上线。下一轮单一可操作编号/审计分离、阅读单位合并及未读候选续接只有设计，生产Add/Search本轮未改。较强Answer改善日期/主体，但漏掉120的费用仍无法答完整总额，ESLint仍混淆建议与落地；不报新总准确率。网页旧评分未覆盖，新报告已入研究入口。凭据依赖/DB未改、未部署/提交。下方“最新”为此前reading轮记录。

最新先读 `docs/doing/2026-10-30-reading-contract-implementation.md`、同前缀run-ledger和`docs/phase-3/2026-10-30-reading-contract-execution-plan.md`。工程实施与本轮验证完成，整体质量未验收。最终146回归＋3子测试；真实公开r2六类12份完整准备历史400/400 Add、36/38 Search/Answer、409/420整理。人工17正确／18未达标／3不确定（19题另读证据）；24同题旧版13正确，r2为11，不能宣称整体提升。两次Search非法位置0；整理5schema／5笔记超限／1来源非法。0额外Query、1read_more，未证明补查收益；阅读预算排除322单位、装箱0。自行车头盔120已召回第33但在24入口处排除，Select未见且未补查。默认生产已收敛短段落／单编号，逐句版本撤回；工具上下界组件仍失败，不采用。

本轮41档案（39新库＋2组件）共4696尝试／4678响应、输入6078963／输出239668tokens；只有12份不同公开历史＋5个控制历史，不能把重复轮次合并准确率。初始沙箱16请求失败及r1两次provider超时保留。r2结束时源码38/38匹配，随后仅修正空开头不得假冒原文锚点的显示；最终版本r3控制10/10 Add、6/6 Search/Answer、2/2整理，146回归通过，公开38题未在此显示小修后重跑。默认DB300核对空并hash备份后建为空DB301；health200版本0.3.1-reading。历史实验不删除／恢复，凭据依赖未变，未部署、未提交。

研究页已构建：11数据集、36理论案例、25深入研究登记、65运行／194问题条目（含重复和失败），不可把页面总数当独立样本准确率；模型完整I/O及失败null可展示。真实原文浏览器访问此前审批拒绝，未绕过；本轮仅文件构建／静态及数据身份校验。

上一版100题基线：方法冻结4191890，六类26份完整准备历史、780/780 Add、100/100 Search、100/100 Answer；Reflection726/732完成（3工具结构、2来源列表、1笔记超限失败）。3607尝试/3607响应，输入5774218、输出223977tokens。mini初评54正确/41未达标/5评分失败；Codex审读全部回答为51正确/47未达标/2不确定，其中22题另读实际证据。公开研究集、无官方成绩/泛化保证。整理完成率不是语义正确率。

此前用户提交0d944b6后确认整合 `benchmark`、`casestudies`、`visualization` 为 `research/`，`dataset/` 保持独立。整合轮仅改native研究导入、不改Add/Search算法、不新增真实模型调用；该轮36案例中16建立深入实测链路，100题保存回答复核。

用户已提交研究整合为 `5a9146a`。实施前根因复核见 `docs/phase-3/2026-10-30-mechanism-audit-and-directions.md`：只读复算100题160次Query／135次Select，重建732次Reflection旧语境。387次有词法匹配旧note却因先全语料前48再筛note而不显示；98题首轮24卡满，35题补查仅8题最终选入首轮未见原文，3题新卡被合并预算截断。路由消融有得有失，不能据此删note／邻接或声称新准确率；诊断在忽略的 `research/data/mechanism30/`。该分析已用于本轮计划，不再是全部待实施。继续遵循用户原则：从模块职责提炼问题，不按特定答案加提示／约束。

## 每次先读

1. 根 `README.md`、`docs/README.md`、`DESIGN.md`。
2. `docs/phase-2/integration-research.md`（比赛背景；上次在线核验不是今日重新核验）。
3. `research/README.md`、`docs/phase-3/2026-10-30-evidence-method-review.md`、`docs/doing/2026-10-30-research-consolidation-implementation.md`。
   最新实施先读上方reading-continuation三份文档；机制分析见`docs/phase-3/2026-10-30-mechanism-audit-and-directions.md`，不要把离线投影对照当真实新模型效果。
4. 实测详见 `docs/doing/2026-10-30-hundred-answer-report.md`、同前缀ledger及 `docs/phase-3/2026-10-30-hundred-answer-execution.md`。按任务需要再读历史长文。

## 唯一研究入口与数据

- `research/benchmark/`：请求适配、执行、Answer/Eval、观测、运行登记与评注。
- `research/cases/catalog.json`：唯一案例身份和理论/实测登记；具体文档在同目录。
- `research/web/`：页面构建，命令 `python -m research.web.build`。
- `research/data/index.html`：唯一生成页面；按运行加载 `runs/*.js`，普通浏览器可离线打开。无独立案例页/百题页；页面选择状态不保存。
- `research/benchmark/data/runs/hundred30-*`、`research/benchmark/data/plans/clean30-hundred-answer/`：原始100题证据与冻结计划。不要改写历史快照里的路径/哈希，不把重放或新代码结果混入旧分母。
- 原文、模型完整I/O、库、生成页面都在忽略data路径。来源标注/gold仅评估侧可见，不能泄入Add/Search。评注按运行/数据/轨迹/步骤绑定，追加保存。

## 核心边界

成功Add表示有效原文、episode、BM25/向量和必要遗忘已原子提交；整理可待处理或不完备。提交前必要操作失败则不留半轮写入；相同request_id同内容重放不重复模型调用，换内容拒绝。Search独立只读已提交记忆，不消费WorkingMemory，不触发Reflection，不执行Answer。模型配置和源码只保留当下真实可用的路径，不引入默认关闭的研究功能或失败时隐藏降级。

已实施有限遗忘确认处理：状态与Add凭据原子持久化，直到下一条普通用户消息；助手确认的被撤销句段不建索引，无关句保留，必要判断失败则接收撤销。历史主题遗忘仍按整条来源，不能宣称全历史精确遗忘已解决。当前缺口：Select证据作用/集合完整性、未读预览已给线索却不展开、跨轮保留与装箱预算、note增量和重复、历史同义主题漏删、外部Answer误读语气／时间和mini评分偏差。旧轮非法0、没有候选续读的记录不代表本轮仍未实现；本轮77次Select合法。先定位这些断点，再讨论恢复图；整体质量未通过。

## 历史保留

一期0.3.0归档在 `archive/phase-1/`，一期已完成比赛并清理部署；二期r11（26/75 Reflection）源码/设计在 `archive/phase-2/20261029-clean-rebuild/`。旧研究页面、19份较早实验、旧计划、过期执行文档及本文件之前的完整项目记忆在 `archive/research/20261030-consolidation/`；没有永久删除。旧资料的“当前/待实施”不是今天状态。新实验使用新库，不恢复旧库起步。

本轮未改私有配置/依赖、未部署、未自动提交。此前真实原文浏览器访问被自动审批拒绝；不得换通道绕过。可在文件工具分析真实数据，UI验证只使用无真实数据的合成fixture。明确区分实际浏览器验证与静态/数据校验。
