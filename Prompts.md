# AML 记忆设计

## 任务1：回顾 1 期设计和构建情况
请阅读 AGENTS.md，探索和分析相关内容/具体编码，然后告诉我，我们 1 期的 AM-Link 是如何设计和构建的？


## 任务2：探查服务器环境和模型调用的基础可用性
请修复 AGENTS.md 路径，然后帮我探查环境是否可用（llm、embedding、服务器），以及服务器 https 证书当前是否还在


## 任务3：数据集和测评环境准备
（A）你可以帮我调研一下比赛官方所用（整合或参考）的数据集有哪些吗？

（B）你可以帮我新建一个目录，命名为 dataset，并有序地组织组织可以获取的相关数据集原始数据，以及相关数据集的切分、读取、处理、使用和评测方式；

（C）然后你可以帮我新建一个目录，作为“靶场”/benchmark，可以使用数据集来初步检验我们的实施，也可以获取 1-2 个开箱即用的开源框架用来比较，如 mem0 （但你不要获取其源码构建，避免抄袭，你应该找能直接提供结构的框架）。（1）靶场应该能够设计得灵活，例如可以支持使用特定数据集、使用少量数据集来进行评估；（2）靶场应该能够设计得可观测，例如能够看到追溯数据的使用，不仅仅能看到得分，更能从结构化的记录中检查和分析原因；（3）靶场应该能够设计得标准，例如就是用比赛官方所设计的 add、search 接口来适配和使用参与靶场的测评对象（我们的实现、mem0）。

请进行充分的调研、分析和设计，将上述要求、执行计划、实施情况写入到 docs\doing，并根据要求进行实施和核对；可以建立主计划记录整体要求，并维护子计划；可以随着探索、调研的深入，重新设计方案或更新计划。请按此开始实施。

## 任务5：链路观测

评估当前真实实验构建的结构化记忆的质量，进一步分析当前真实链路所观察的方法设计或实现问题，特别是是核心方法（引用、结构化记忆、bfs 多跳、working memory 缓冲、多特定问题切分 query、select 精炼、reflection）是否有效

## 任务4：核心设计

你的初步分析基本合理、但细节上还是不够干净收敛，以及我还有一些新的思路继续讨论；我们这一轮重构范围很大，设计也几乎等于重新设计，可以计划调整为实施时归档当前 AM-Link并重新实施。

请重新加载 AGENTS.md 回顾项目背景，并继续结合 TinySoul 项目编码理解和探索 TinySoul 设计原理；然后让我们继续讨论、设计和修订 AM-Link 重构方案、设计理念和执行计划。

让我重新定义概念，如果要引入新设计语义，请先和我说明确认；

（1）结构化记忆 MemoryItem：指 `episode/person/entity/concept/event/fact` 类型的记忆节点，以及之前的关联关系 MemoryRelation；

（2）引用 References：类似 TinySoul，对于模型可见包含两部分，1 是引用格式（不是随机编码，有语义）， 2 是对于引用的模型叙事，例如说明解释、query 语义命中片段、关键词命中片段等；以下说明引用 References，这两部分要求同时作为 llm 输入或相关算子输出，避免孤立、缺失含义的引用链接。

（3）记忆语境：参考 TinySoul，llm 调用可以看作： context+input->llm->tool calls，在记忆系统里，context 就是记忆语境，包含当前活跃（模型可见）的结构化记忆 content of MemoryItem，以及待处理的工作记忆缓冲区 MemoryWorking；tool calls 就是我们需要 llm 做的决策或者生成内容。

（4）检索 Search：根据 question 返回记忆的行为，由多个步骤复合而成；

（4.1）在这里先说精炼 Select，它使用模型 llm，输入上下文语境（例如已有记忆和 question）+ 一组候选 References，输出（可重排的） References 子集。seed 这个概念不存在；精炼 Select 的目的是接在 Query 和 Backlinks 之后，因为它们输出一组 References，但有时可能 References 数量过多，因此需要 Select 进行语义精炼。下面流程编排了就不提 Select 了，把它作为 Query 和 Backlinks 在输出较多 References 之后的默认算子；

（4.2）Query(question)->References(->Select)->References，主要方法为 BM25+Embedding，目的是“从无到有”都根据问题 question 找到相关的记忆语境；更进一步的设计，通过多通道 Query 使对于某类 Item 查询有所倾向/让 Query 粒度更细致，例如，在 search 开始时，使用一次 llm(question+context)->question1、question2...，再收集合并 Query(question1)、Query(question2)... 作为 Query 的输出 References（再一起 Select）

(4.3)Inspect(ref)->Item content（包含正向引用）

（4.4）Backlink（ref）->References(->Select)->Item content of References

(4.5) BFS：Inspect、Backlink 的多跳迭代，从而通过正向和反向引用将 Item 补充到记忆语境

（4.6） 最终 Search 结果：待定，可以通过 llm 来给出与最终 Search 相关的 References，然后再确定地并 References 指向的 Item content 展开作为完整 Search 结果；也可以考虑让 llm 参与对结果的分析，例如 question+context->llm->answer of question；因为 context 只存在与我们记忆系统内部，与外部的交接和解释只有标准 add/search 两处；

（5）Add 和 Relection 编排：

（5.1）把标准 Add 输入存储到缓冲区 MemoryWorking；但此时，我的新设计是，考虑到 Add 并发，我觉得需要把 Add->MemoryWorking 和 MemoryWorking+Context->MemoryItem 解耦；首先，你得去了解一下官方的 Add 并发数（应该是 4），以及 Add 最大时间；把记忆系统理解为生成消费，Add 加入 MemoryWorking，Relection 消费 MemoryWorking；Relection 可以持续在后台运行，与 Add 解耦，并具有三种状态：停止、MemoryContext 维护、MemoryItem Mutation

（5.2）状态转换：当 MemoryWorking 更新时，系统由停止进入 MemoryContext 维护，在此阶段下（可以作为微型 loop 迭代）由 llm 决策：Search(question) 来回忆并添加内部 context 语境、Evit(Item of context) 来逐出内部 context 语境（或压缩）、以及状态转移（停止或进入 MemoryItem Mutation）；此外，进入 MemoryItem 更新也可以由特定条件触发或提示 llm 进行决策（特别是会话切换的情况），但需要合理设计，如充分、有序完成进行的 MemoryContext 维护后进入 MemoryItem Mutation；

（5.3）在结构化记忆 MemoryItem Mutation 阶段，更新、删除、新增 MemoryItem 并维护关联等等，（可以作为微型 loop 迭代）由 llm 决策重新进入维护或者停止。

请进一步据此分析、设计理想的 AM-Link 架构和方法，重新梳理方案、设计理念和执行计划，然后向我阐述设计和流程编排（以形象可视、详实易懂的方式），并继续和我讨论确认。


你的分析和设计合理，请持续修订计划和设计理念，下面是我的分析：
（1)官方作为评测，一般是先批量完成全部 add，再统一 search；因此，尽量把 add 持续时间拉长更好，例如，在内部处于停止状态时再返回 add 200（即在 Reflection 尚未完成时不返回）；
（2）避免并发 Add 造成同一用户的 Reflection 相互覆盖合理，add 可以并发加入，但我们内部应当稳定、顺序（即同用户采用串行 Reflection 和处理水位）；此外，你提到 user_id，当前 add 接口有这个字段吗（及其含义），我觉得使用场景很可能是多次连续同 id 的 add 再换 user id，因此根据 user_id 设计并行可能过于复杂、没有必要；
（3）你的新理解“Query 的分支先合并再 Select；BFS 每层的 Backlink 候选先合并，过多时再 Select；Inspect 本身不做 Select 合理，你可以把这个 Search mermaid 画到设计理念；一个注意点是 BFS 这里是继续 Inspect、还是 Backlink、或者是停止应该使用 llm 来决策和生成参数（通过工具调用和轻度 loop）；以及 loop 的含义是，Inspect->item content、backlink->select->refs->item content 会立即加入 context 并影响后续 BFS，例如，可以出现 Inspect（ref1 of item1)->context 获得 item1 content，包含 ref2 of item2-> Inspect（ref2 of item2)，从而实现这样的多跳路径；
我还可以举出另一个路径示例（这些路径应该由 llm 在 loop 中根据 memory context 灵活决策）： Backlink（ref1 of item1)(->结果多，默认Select）-> context 获得 refs（包含解释或片段）->Inspect(ref2 in refs) 
请继续分析、设计，然后修订文档和计划。在此基础上，请全面分析设计理念是否清晰明确、执行计划是否合理可行；你可以继续向我阐述设计和流程编排，若有不明确的设计语义/决策点继续讨论确认。
