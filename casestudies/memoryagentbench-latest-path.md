# M01：沿着最新关系走三步

日期：2026-10-07；来源核对、完整事实列表切片、本地词法检索 done。

来源：[MemoryAgentBench](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench)，本地 `Conflict_Resolution` Parquet 第 0 行，`metadata.source=factconsolidation_mh_6k`，问题 0。原文件与 SHA 在研究 pack 的 preparation 中，问题完整原文保留本地。数据卡 MIT 不替代混合子来源的独立许可核对。

## 材料内的世界

问题：小说 Our Mutual Friend 作者的配偶，其国籍是什么？材料故意改写事实，不可用现实世界知识纠正它。

| 属性 | 较早事实 | 后来事实 |
| --- | --- | --- |
| 小说作者 | 107：Charles Dickens | 146：Charles Darwin |
| Charles Darwin 的配偶 | 164：Emma Darwin | 335：Amala Paul |
| Amala Paul 的国籍 | 294：India | 322：Belgium |

当前链是 **小说 → Charles Darwin → Amala Paul → Belgium**，与作者答案一致。这里以材料给出的序号作为事实更新顺序。并非把所有任务统一规定为“后说的一定对”；现实未解决冲突仍应保留双方证据。

## Add / Search / Answer

Add 将 455 条编号事实按顺序保存。派生记录至少区分主体、关系、对象、版本、原句及序号；更新只作用于相同主体关系，不能覆盖这个实体的其他属性。

Search 首轮找到作品作者；据返回证据扩展查找 Charles Darwin 的配偶；再查 Amala Paul 的国籍。每跳都选择材料内当前版本，并保留旧值及更新依据。返回三条连通证据后，Answer 才能得到 Belgium。

可检验失败：直接对原问题做一次 top-k，通常命中关于书和作者的句子，问题正文没写配偶姓名，所以第三跳可能得分为零。把 k 增大不等于已经实现链式检索。

## 已运行对照及边界

`benchmark.lexical_study` 对完整 455 条事实执行 BM25 top-5，原始排名保存在 `benchmark/data/research/lexical-longmem.json:mab_case`。三条必要路径由人工核对，不能称为全数据集官方 evidence 金标。

本研究包只适配冲突类的这条编号事实记录。四类源数据共 146 context / 3,671 questions：准确检索 2,000，冲突解决 800，长程理解 171，测试时学习 700。context 不是一道问题；同一 context 下的问题不能随意拆进独立训练/测试组。

测试时学习的首条任务答案是电影 entity ID，需要 `entity2id.json` 映射；其余记录含大量分类示例。若统一用普通字符串短答案判分，会把任务语义处理错。长程理解则有长摘要和关键点，不适合只报 top-k 源句召回。
