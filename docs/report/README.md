# 记忆研究分享报告

这里是面向分享和讲解的数据集、样本与记忆链路材料，不以当前 AM-Link 版本为主线。报告先解释数据长什么样，再用小案例说明记忆为什么会失效，最后把 Mem0 和 AM-Link 的真实观测放回 Add/Search/Answer 链路中。

## 入口

- [交互式数据与案例展示](./index.html)：适合现场讲解，可按数据形状、案例和链路阶段查看。
- [研究报告底稿](./研究报告.md)：适合继续编辑、打印或拆成演讲稿。
- [2026-10-14 真实模型链路补充实验](../../archive/research/20261030-consolidation/docs/doing/2026-10-14-real-model-chain-report.md)：逐案例记录 Mem0 与 AM-Link 的 Add、Search、独立 Answer，以及失败发生的阶段。

直接用浏览器打开 `index.html` 即可离线讲解；页面内置数据集说明、15 个精选案例和 LM04 证据勾选演示，没有模型调用。案例详情把理论链路与已有 Mem0/AM-Link 观察放在同一处；没有运行记录的案例会明确标成未验证。页尾的项目文档链接需要保留当前目录位置；只复制 HTML 到别的电脑时，主要展示仍可用，项目内链接需要一起复制对应文档。

## 内容边界

- 数据集规模、字段和标注来自本地数据核验与 `research/web/research.json`；缺失的原始材料不会被补写成“已取得”。
- Mem0 短例来自 `research/cases/mem0-microstudy.md`，是受控小实验，不是全量准确率。
- AM-Link 运行来自 [2026-10-14 100题重跑复核](../../archive/research/20261030-consolidation/docs/doing/2026-10-14-amlink-100-rerun-review.md)、[2026-10-14 真实模型链路补充实验](../../archive/research/20261030-consolidation/docs/doing/2026-10-14-real-model-chain-report.md) 和跨数据集切片；HTTP 成功率不等于回答正确率。
- 网页只保存用于讲解的聚合数据和短案例，不嵌入原始长历史、私有凭据或完整运行轨迹。

## 更新方法

新增数据集或案例时，先更新根目录的 `research/cases/catalog.json`、案例 Markdown 和统一可视化，再把适合分享的事实同步到本目录。每个案例旁同时说明理论链路和 Mem0/AM-Link 实测边界；没有来源或没有运行记录的地方写“未验证”。

页面案例是 catalog 的精选快照，运行 `python docs/report/build_cases.py` 同步。精选名单和实验讲解位于脚本中；来源绑定仍以 catalog 为准。数据集规模及运行统计是带日期的报告快照，需要依据新研究记录人工修订，不会自动变成“最新成绩”。
