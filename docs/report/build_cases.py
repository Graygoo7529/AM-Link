"""从唯一案例 catalog 同步分享页的精选案例；不读取原始数据或运行凭据。"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = Path(__file__).with_name('index.html')
SELECTED = ('b1', 'b2', 'b3', 'lm4', 'lm5', 'lm2', 'lm3', 'l4', 'p1', 'p2', 'm1', 'c2', 'pv3', 'pv4', 'v31')
NAMES = {'beam': 'BEAM', 'longmem': 'LongMemEval', 'locomo': 'LoCoMo',
         'persona': 'PersonaMem-v2', 'pv3': 'PersonaMem-v3',
         'perltqa': 'PerLTQA', 'mab': 'MemoryAgentBench', 'life': 'CL-bench Life'}
OBSERVATIONS = {
    'b1': ('案例理论', '这是明确更新的讲解案例；与 B02 的相反经历对比，不能把所有后说的话都当作覆盖旧事实。', None),
    'b2': ('真实观察', '2026-10-08 AM-Link 已返回相反来源，但诊断回答先给肯定结论再表达保留。断点也可能位于 Answer。', '2026-10-08-amlink-answer-research.md'),
    'b3': ('真实观察', '2026-10-14 独立真实运行：Mem0 Add 仅 7/37 成功，正式链路因写入未完成而跳过 Answer；对成功 Search 做的后验 Answer 仍给出五个相关、却不是标注顺序的实现主题。AM-Link Add 10/37 成功，Search 成功但独立 Answer 同样偏离标注顺序。失败首先发生在长历史 Add/Reflection，其次发生在 Search 的顺序证据覆盖。', '2026-10-14-real-model-chain-report.md'),
    'lm4': ('真实观察', '跨数据集 Mem0 诊断回答 $65，虽然此前记录中可见头盔事实；另一次 AM-Link 诊断答 $185。条件不同，不是系统排名对照。', '2026-10-08-memory-research-survey.md'),
    'lm5': ('真实观察', '2026-10-08 AM-Link 诊断取到分子、分母后，Answer 得到 20%。这是单题观察。', '2026-10-08-amlink-answer-research.md'),
    'lm2': ('真实观察', 'Mem0 日期前缀短例仍把一侧事件日期概括为 recently，未能完成日期计算；另需区分间隔天数与首尾日计数。', None),
    'lm3': ('真实观察', '2026-10-14 Mem0 与 AM-Link 都完成 Add/Search/Answer；两者都返回猫 Luna 的相关证据并正确拒答仓鼠姓名。', '2026-10-14-real-model-chain-report.md'),
    'l4': ('真实观察', '2026-10-08 的 AM-Link 回答列出电影，遗漏甜点等共同项。核验应同时看两人的证据和输出是否完整。', '2026-10-08-amlink-answer-research.md'),
    'p1': ('真实观察', '2026-10-14 Mem0 与 AM-Link 都完成 Add/Search/Answer；两者都答出张小红的兄弟是张小明，AM-Link 还保留“弟弟”的方向和关系语义。', '2026-10-14-real-model-chain-report.md'),
    'p2': ('真实观察', 'PerLTQA P02 的 AM-Link 切片在 Reflection 关系校验阶段阻断，不能把作者答案当作记忆事实，也不能评价最终回答。', '2026-10-08-amlink-answer-research.md'),
    'm1': ('真实观察', '2026-10-14 两套系统都完成 Add/Search；Mem0 的 Answer 明确说证据不足，AM-Link 也指出 Dickens 配偶国籍无法从证据得到，并识别了无关冲突。该 pack 没有统一 gold answer/evidence，不能当作准确率。', '2026-10-14-real-model-chain-report.md'),
    'c2': ('真实观察', '2026-10-14 两套系统都完成 Add/Search/Answer，但都把税务适用条件补全为一般规则；AM-Link 明确加入了未在证据中出现的 punitive damages/pain and suffering，说明断点在 Answer 的条件推理。', '2026-10-14-real-model-chain-report.md'),
    'pv3': ('真实观察', '2026-10-14 Mem0 Add 8/15 成功、1/2 Search 成功，正式链路无 Answer；后验 Answer 对 housewarming 问题明确说现有证据不足。AM-Link Add 0/15（10 次 forget_requires_explicit_new_user_instruction，另有 schema/reflection 错误），但失败 Add 仍在数据库留下部分 raw/node/edge，Search 2/2 后只能回答通用保险建议。敏感信息最小化、事务回滚和长期遗忘仍未被验证。', '2026-10-14-real-model-chain-report.md'),
    'pv4': ('尚未取得回答结果', '2026-10-08 AM-Link 此例在 Add/Search 阶段受阻，不能判定遗忘是否成功。Mem0 未先存园艺偏好的观察来自另一个 PV02 短例。', '2026-10-08-amlink-answer-research.md'),
    'v31': ('真实观察', '2026-10-14 Mem0 与 AM-Link 都完成 Add/Search；Mem0 Answer 给出三条与幽默游戏内容相关的推荐，AM-Link 只装箱了两条游戏/幽默候选。该切片没有统一 gold answer，结果用于观察证据范围和推荐装箱，不作准确率。', '2026-10-14-real-model-chain-report.md'),
}
EXPLANATIONS = {
    'b1': {
        'concept': '知识更新：同一件事后来被明确改写',
        'why': '问题问的是“现在”每天有多少次调用。历史里同时出现每天 1,000 次、每分钟 60 次，以及后来的每天 1,200 次；如果只按相似度找一句，容易把单位混在一起，或者把旧值当成当前值。',
        'theory': 'Add 应保存项目、属性、单位、发生顺序和来源。Search 先找到同一属性的多个版本，再依据“后来明确改写”保留 1,200，同时让人还能追溯到 1,000。B01 可以形成 supersedes；它和 B02 的相反经历不同，不能因为后一句出现就自动覆盖。',
        'mem0': '没有针对 B01 做独立 Mem0 运行；它主要作为“更新”和“冲突”的对照案例。',
        'amlink': '没有把这个中文转述案例当作整体准确率实验。设计检查应看：旧值是否还在、当前值是否有来源、每天和每分钟是否被分开。',
        'lesson': '更新不是删除历史，而是给新旧事实建立可解释的时间关系。',
    },
    'b2': {
        'concept': '冲突：两句话都像事实，却不能强行选一边',
        'why': '一段历史说项目 Key 已在 2024-03-10 取得，另一段又说从未真正取得。它不像 B01 那样给出清楚的“新值替代旧值”，所以系统不能自行编造“后来失效”或“换了项目”。',
        'theory': 'Add 保留两条原文和主体、时间、来源，建立 contradicts 或待澄清状态。Search 必须把冲突两端一起交给 Answer；Answer 应先说记忆中存在两种说法，再请求澄清，而不是把排序第一条写成确定结论。',
        'mem0': '本次短例没有覆盖这个 BEAM 冲突案例。',
        'amlink': '真实诊断中 AM-Link 已返回两条相反来源，但 Answer 先以“Yes”开头，之后才补充冲突。说明 Search 可能已经成功，错误仍会发生在答案表达。',
        'lesson': '把两条都找到只是检索成功；是否诚实地交代不确定性，是另一道题。',
    },
    'lm4': {
        'concept': '跨会话聚合：多个会话里的提及要合并成几笔事件',
        'why': '“跨会话”指问题发生在当前会话，但答案所需的材料分散在以前多次独立对话中。LM04 有四个标注来源：链条 25 美元、车灯 40 美元、头盔 120 美元，车灯还被重复提到。重复的句子不应变成第二笔消费。',
        'theory': 'Add 先保留每条原文及会话日期，再把“消费事件”和“再次提及”区分开。Search 不能只找最像“自行车”的一句，要收齐不同物品的证据，并在必要时 Inspect 来源。Answer 再按事件去重后求和，得到 185 美元。',
        'mem0': '跨数据集 Mem0 诊断曾回答 65 美元。观测中此前出现过头盔事实，因此不能只凭最终答案断言是保存失败；可能是候选、Answer 上下文或组合阶段丢失。',
        'amlink': '另一次 AM-Link 诊断 Search 返回四条结果并覆盖四个标注来源，Answer 得到 185 美元。这个结果说明完整证据可以支持聚合，但和 Mem0 的输入、系统、运行条件不同，不能直接排名。',
        'lesson': '“命中相关句子”不等于“交付了可计算的证据集合”；跨会话问题最需要来源和事件身份。',
    },
    'lm5': {
        'concept': '证据槽位：比例题必须同时拿到分子和分母',
        'why': '历史分别说女性占 20 个领导岗位、公司共有 100 个领导岗位。20 本身不是比例；如果 Search 只返回第一句话，模型很容易把缺失的分母猜出来。',
        'theory': '把问题拆成“女性领导岗位数”和“领导岗位总数”两个证据槽位，核对公司、时间和统计口径，再交给 Answer 计算 20 ÷ 100 = 20%。缺少任一项时应说明证据不足。',
        'mem0': '没有把 LM05 纳入 Mem0 六条件短例；它作为复合证据的理论案例。',
        'amlink': 'AM-Link 的单题诊断拿到了 20 和 100，Answer 得到 20%。这说明证据覆盖达到要求时，下游计算很简单；关键不是让模型“更会算”，而是 Search 不要漏掉分母。',
        'lesson': '复合问题应该先问“还缺哪个槽位”，再问“哪条最相似”。',
    },
    'lm2': {
        'concept': '时间推理：日期必须作为内容和来源一起保留',
        'why': '“相隔几天”看起来像简单减法，但历史中的“上周日”和“昨天”只有放回原始会话日期才有意义；还要区分精确时长、日历日差和首尾计数。',
        'theory': 'Add 保存原始日期、时区假设、说话者和事件内容，不能只保存“最近”。Search 交付两件事的完整时间证据；Answer 明确采用哪种计算口径，并在口径不同的评测中解释差异。',
        'mem0': '加入日期前缀后，Mem0 保留了大都会日期，但把另一侧压成 recently，因此仍无法可靠计算。日期进入输入不保证日期进入记忆。',
        'amlink': 'AM-Link 诊断拿到 UTC 时间戳，并算出约 6.5 天；数据集参考按日期差记为 7 天、首尾计数为 8 天。这里暴露的是口径和 Answer 解释问题，不是单纯的向量召回失败。',
        'lesson': '时间字段不是装饰性 metadata；一旦被摘要成“最近”，后面的推理就失去锚点。',
    },
    'b3': {
        'concept': '顺序约束：答案不仅要全，还要保持原来的次序',
        'why': '题目要求列出城市自动补全功能讨论中依次出现的五个实现关注点。防抖、慢响应、快速输入、下拉与错误、监听器清理都可能在相似的代码片段里反复出现，少一个、重复一个或重新排序都会改变任务含义。',
        'theory': 'Add 保存每次讨论的主题、会话来源和出现顺序，不能只保存最后一段总结。Search 先收齐五个阶段，再按来源顺序交付；Answer 负责检查数量和顺序，不要用相似的错误处理句子替代缺失阶段。',
        'mem0': '2026-10-14 独立运行把 200 轮历史切成 37 次 Add，但只有 7 次成功；正式运行因 Add setup 未完成而跳过 Answer。对成功 Search 的结果做后验 Answer 后，模型列出防抖、慢响应、特殊字符、输入/错误区域和 async/await 五个相似主题，仍未恢复标注顺序。失败发生在长历史写入/模型处理阶段，后验结果又说明 Search 证据集合不完整。',
        'amlink': '同一切片的 AM-Link 37 次 Add 只有 10 次成功，错误主要是 `forget_requires_explicit_new_user_instruction`。Search 最终返回 5 个事实，但它们是“性能、错误处理、加载动画、定制实现、输入校验”等相似主题；独立 Answer 将这五项按相关性列出，完全没有恢复标注要求的“防抖→慢响应→快速输入→下拉/错误→监听器清理”顺序。这里既有 Add/Reflection 丢批，也有 Search 未保住顺序槽位的问题。',
        'lesson': '有些题目要的不是最相关的几句话，而是一条不可打乱的过程记录。',
    },
    'lm3': {
        'concept': '拒答：相关证据存在，但目标实体没有答案',
        'why': '历史明确说用户的猫叫 Luna，问题问的却是仓鼠叫什么。猫名是相关材料，却不能被扩大解释成仓鼠名；如果系统只看“宠物姓名”的相似度，就会产生看似流畅的错误回答。',
        'theory': 'Add 保存物种、主体和姓名之间的绑定。Search 可以返回猫 Luna 作为边界证据，同时确认没有仓鼠姓名；Answer 应明确拒答并解释 Luna 属于猫，而不是把空目标证据当作检索失败。',
        'mem0': 'Mem0 Add/Search/Answer 均成功，返回猫 Luna 作为唯一相关证据，Answer 说仓鼠姓名未知；它正确区分了相关宠物与目标宠物。',
        'amlink': 'AM-Link Add/Search/Answer 均成功，返回猫 Luna 的证据，Answer 说检索记忆没有仓鼠姓名。两套链路都说明拒答可以建立在“找到相近实体但缺少目标实体”之上。',
        'lesson': '拒答不是没有召回，而是召回结果不足以支持问题中的那个实体。',
    },
    'p1': {
        'concept': '人物关系：方向和主体比关键词更重要',
        'why': '问题问“张小红的兄弟是谁”。材料表达的是张小红有一个弟弟张小明；如果只记住“小红、小明、兄弟”几个词，可能反转关系，也可能把另一个档案中的同名小明合并进来。',
        'theory': 'Add 保存 subject、relation、object、方向和来源。Search 先确认问题主体是张小红，再 Inspect 关系正文；Answer 只输出有来源支持的“张小明是她的弟弟”，不把关系方向改写成相反说法。',
        'mem0': '2026-10-14 Add/Search/Answer 全部成功，Answer 为“张小红的兄弟是张小明”。它没有显式说明“弟弟”方向，但没有把关系主体反转。',
        'amlink': '同一运行 Add/Search/Answer 全部成功，Answer 为“张小红的兄弟是张小明，他是张小红的弟弟”。Search 交付的关系证据和 References 叙事保住了方向，说明结构化关系在短链路上确实有帮助。',
        'lesson': '关系记忆不是关键词列表；主语、宾语和箭头方向本身就是证据。',
    },
    'p2': {
        'concept': '原文与标注冲突：不要用标准答案修复历史',
        'why': '事件记录说 5 月 12 日出发，同一天对话又说“昨天抵达”，作者答案则写成 5 月 12 日抵达。题目真正有价值的地方，正是让我们看到原文、日期和评估答案并不总是一致。',
        'theory': 'Add 只能保存事件、对话时间和原句，并把相互矛盾的时间留在关系中。Search 同时交出冲突两端；Answer 可以说“对话称已抵达，但具体日期前后矛盾”，不能把 gold answer 倒灌成历史事实。',
        'mem0': '没有把 P02 纳入 Mem0 短例。',
        'amlink': 'P02 的真实切片在 Reflection 用非法 `about` 关系连接 episode 与 person 时被 schema 校验阻断，未进入 Answer。因此当前只能定位到 Add/Reflection 协议断点，不能评价回答效果。',
        'lesson': '评估标签是核验材料，不是可以替原文改写记忆的“真相修复器”。',
    },
    'm1': {
        'concept': '三跳关系：每一跳都可能有旧值和新值',
        'why': '题目要的是“作品 → 最新作者 → 作者的配偶 → 配偶国籍”。材料故意让作者、配偶和国籍各有旧版本与新版本；只做一次相似度检索，通常只能找到第一跳，或把三条旧边混在一起。',
        'theory': 'Search 先找到最新的作品作者，再 Inspect 作者节点，继续 Backlink/Inspect 得到配偶和国籍；每一跳都保留来源编号和版本状态。Answer 只依据题内材料得到 Belgium，不用现实世界常识纠正它。',
        'mem0': '2026-10-14 Add/Search/Answer 全部成功；Answer 说证据中没有 Charles Dickens 配偶国籍，并避免用检索到的 Darwin/Amala Paul 冲突替代目标答案。',
        'amlink': '同一运行 Add/Search/Answer 全部成功；Answer 识别 Dickens 是《Our Mutual Friend》作者，同时指出配偶国籍证据缺失，并把 Darwin/Amala Paul 的冲突标为无关。该 pack 没有统一 gold answer/evidence，所以这是可观测的三跳实例，不是准确率结果。',
        'lesson': '多跳不是把 top-k 加大；每一跳都要更新当前状态并保留可回指的来源。',
    },
    'c2': {
        'concept': '条件推理：缺少适用条件时，答案应该保留分支',
        'why': '第二笔和解金里，损失扶养 65 美元、一般损害 435 美元、利息 2,000 美元的规则不同；但一般损害是否源于身体伤害这一条件没有提供。若系统只召回金额，就会把 435 美元也武断归入同一税务结论。',
        'theory': 'Add 将规则、金额、当前案件和适用条件分别保存。Search 同时召回规则和案件事实；Answer 可以确定 65 和 2,000 的处理，对 435 给出条件化说明，并指出需要补充的事实。',
        'mem0': '2026-10-14 Add/Search/Answer 全部成功，但 Answer 把一般损害、利息和损失扶养按常见规则分类，并补充了题内没有给出的条件判断；它给了一个流畅答案，却没有把“适用条件缺失”作为主要结论。',
        'amlink': '同一运行 Add/Search/Answer 全部成功；Answer 除了把利息和损失扶养列为可课税外，还加入题内证据没有出现的 punitive damages 和 pain and suffering。这里 Search 有证据，断点在 Answer 的条件推理与证据边界。',
        'lesson': '“不知道条件”不是噪声，而是答案的一部分；好的记忆系统要把未知保留下来。',
    },
    'pv3': {
        'concept': '敏感信息：当前任务能用，不等于应该长期记住',
        'why': '保险理赔清单可能包含社会安全号码和材料传输信息。系统可以在当前请求中给出遮盖、最小化和官方渠道建议，却不应该把原始号码沉淀成长期用户画像，之后又在普通回答中复述。',
        'theory': 'Add 在写入边界区分当前敏感任务和可长期保留的安全偏好，默认不保存原始标识。Search 只返回必要的脱敏规则；Answer 给安全建议而不复述秘密，并记录过滤是否生效。',
        'mem0': '2026-10-14 PersonaMem 长历史运行 15 次 Add 仅 8 次成功，2 次 Search 只有 1 次成功；正式运行因 Add setup 不完整没有 Answer。对成功 Search 的 housewarming 问题做后验 Answer 时，模型明确说五条证据没有具体礼物建议。失败首先发生在长历史 Add/检索边界，不能把“没有泄露号码”当作遗忘成功。',
        'amlink': '同一切片 15 次 Add 全部返回失败（10 次为 forget_requires_explicit_new_user_instruction，另有 minimum_episode_immutable、duplicate_ref、schema、unknown_source、reflection_incomplete），但失败请求仍留下部分 raw/node/edge，Search 仍返回两组证据。独立 Answer 只给通用保险清单和安全传输建议，未复述 SSN；这只能说明输出层没有复述，不能证明底层没有保存，且暴露了失败事务未完全回滚的实现风险。',
        'lesson': '记忆的边界包括“是否应该保存”，而不仅是“能否找回来”。',
    },
    'l4': {
        'concept': '多跳与完整性：共同兴趣要分别找到两个人的证据',
        'why': '问题不是“Joanna 喜欢什么”或“Nate 喜欢什么”，而是两个人的兴趣交集。7 个来源分散在多次会话里，某一条高相似结果只能证明一个人提过某件事。',
        'theory': 'Query 可以分别围绕 Joanna 和 Nate 找候选，Select 不能因为一条电影证据很像就丢掉甜点证据；BFS/Inspect 继续展开相关人物和兴趣节点。最后把两人的证据分组，再求交集，并给每个结论保留来源。',
        'mem0': '没有把 L04 纳入 Mem0 六条件短例。',
        'amlink': 'AM-Link Search 的 7 个标注来源都出现在 top-5 结果中，但诊断 Answer 仍只回答电影，遗漏共同做甜点。说明“召回完整”与“回答完整”之间仍有断点。',
        'lesson': '多跳系统不能只记录走过多少步，还要检查每个问题实体和答案槽位是否都被覆盖。',
    },
    'pv4': {
        'concept': '遗忘与主体边界：不再使用旧偏好必须可验证',
        'why': '用户曾喜欢手工艺品，后来明确要求忘记；新问题却只是请推荐乔迁礼物。系统既要尊重撤回，也要继续提供不依赖旧偏好的普通建议。',
        'theory': 'Add 把撤回当作状态变更，记录作用域，并检查旧原文、摘要、向量、缓存和关系是否都失效。Search 不能返回被撤回偏好；Answer 可以给通用建议，但不能假装已经证明删除完成。',
        'mem0': 'Mem0 的 PV02 园艺短例中，待删除偏好一开始就没有被写入；回答不再提它不能证明真正执行了删除。',
        'amlink': 'AM-Link 的 PV04 切片在 Add/Search 阶段受阻，没有进入 Answer。因此目前只能说协议阻断了评估，不能宣称遗忘成功或失败。',
        'lesson': '“没有说出来”可能是删除成功，也可能是从未记住；遗忘必须先确认存在，再检查全链路残留。',
    },
    'v31': {
        'concept': '时间切片与未来信息泄漏：知道不该提前看到什么',
        'why': 'PersonaMem-v3 同时有活动事件、提问和未来反馈。提问后的点击或作者生成的偏好标签可以帮助评估，却不一定是当时智能体已经看见的历史。',
        'theory': 'Add 只接收严格早于提问时间的事件，保留动作和时间；Search 使用当时可见的上下文，不把未来反馈倒灌；Answer 只能根据可见证据给推荐，并说明推断范围。',
        'mem0': '2026-10-14 Add/Search/Answer 完成；Answer 从返回记忆中列出三条游戏/幽默候选。由于此切片没有统一 gold answer，不能判断推荐是否最优。',
        'amlink': '同一切片 Add/Search/Answer 完成；Search/装箱只交付两条游戏/幽默候选，Answer 因此只推荐两条。这个差异说明最终证据装箱预算会直接改变推荐覆盖；本切片没有统一 gold answer，结果用于观察可见证据范围。',
        'lesson': '记忆研究不仅问“能不能找到”，还问“当时是否有资格知道”。',
    },
}


def main() -> None:
    catalog_path = ROOT / 'casestudies/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    cases = []
    for key in SELECTED:
        source = catalog['cases'][key]
        level, finding, document = OBSERVATIONS[key]
        explanation = EXPLANATIONS[key]
        case_id, title = source['name'].split(' ', 1)
        cases.append({
            'id': case_id, 'title': title, 'dataset': NAMES[source['data']['dataset']],
            'q': source['q'], 'raw': source['left'] + '；' + source['right'],
            'need': source['add'], 'fail': source['trap'],
            'route': 'Add：' + source['add'] + ' → Search：' + source['search'] + ' → Answer：' + source['answer'],
            'source': source['source'], 'document': source['document'],
            'evidence': source.get('evidence_plan', []),
            'level': level, 'finding': finding,
            **explanation,
            'observationUrl': ('../doing/' + document) if document else ('../../casestudies/mem0-microstudy.md' if key == 'lm2' else None),
        })
    payload = json.dumps(cases, ensure_ascii=False, indent=2).replace('<', '\\u003c')
    html = PAGE.read_text(encoding='utf-8')
    html, count = re.subn(r'const cases=\[.*?\];\s*(?=const caseList)', lambda _: 'const cases=' + payload + ';\n', html, count=1, flags=re.S)
    if count != 1:
        raise SystemExit('页面案例区块不存在；未写入。')
    PAGE.write_text(html, encoding='utf-8')
    print(f'Updated {len(cases)} report cases from casestudies/catalog.json')


if __name__ == '__main__':
    main()
