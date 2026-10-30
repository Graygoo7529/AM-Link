# Mem0：六条件短片段实测

2026-10-07，run `mem0-microstudy-20261007`，done。对应 LM01–03、PV01–02；五个来源案例中 LM02 分“无日期 / 正文日期前缀”两个条件。由用户明确授权后执行，不是完整数据集评测或 Mem0 默认配置复现。

## 固定条件与实际成本边界

- Mem0 OSS `2.2.1`，gpt-4o-mini 抽取及本地 Answer，embedding-3 / 512 维，本地 Qdrant，无重排、无 SDK 重试。每条件独立 user，同条件多个 session 共用 user；session 仅作 metadata。
- 用作者证据辅助选出必要片段，没有干扰历史；答案与标注未给 Add/Search/Answer。日期条件只在正文前加来源日期。
- 10 次 Add、6 次 Search、6 次 Answer；41 次实际模型请求（16 completion、25 embedding），0 请求失败，371,647 输入字符；provider 返回 80,882 input tokens、1,091 output tokens。费用未取得可靠计价，保留未知；没有按零元报告。
- Add 延迟 p50 3,901.524 ms；Search p50 183.344 ms。只是单次短例运行，不是服务容量或长历史延迟结论。
- 可观测文件有 63 个实际 span；每次 Add 后读取记忆快照。凭据没有写入产物，telemetry 关闭。没有部署记忆服务。

## 逐例观测与归因

| 条件 | 实际现象（中文转述） | 能据此判断什么 |
| --- | --- | --- |
| LM03 拒答 | 记住猫叫 Luna；问仓鼠名字，回答未知 | 本例类别边界保留成功。Search 非空也可以正确拒答 |
| LM02 无日期 | 大都会“今天”变成运行日 2026-10-07；MoMA 只有 recently，最终不能计算相隔几天 | 输入适配缺少日期锚点，不能算纯检索失败 |
| LM02 日期前缀 | 原文带 2023-01-08 / 01-15；记忆保留大都会 01-15，却仍把 MoMA 压成 recently；最终仍不能计算 | 日期进入输入不保证进入记忆。丢失点可定位到抽取产物，检索返回这些记忆也无法补回 |
| LM01 更新 | 新旧成绩两条并存，25:50 排第一、27:12 第二；回答 25:50 | 本次回答正确；不能仅因旧值仍在就判错。但输出未给明确的 supersedes 关系 |
| PV01 他人信息 | 只记用户请润色 Mark 简介，没有记成用户养植物；回答却说不知道如何让房间更清新 | 未见归属越界。统一 Answer 提示“只用记忆”对开放建议过严，问题出在本地回答协议，不能冒充 Mem0 的归属失败 |
| PV02 遗忘 | 第一次只记“想在家放松并多接触户外”，未保存园艺偏好；第二次无变更；回答未沿用园艺 | 未见遗忘违例，但待删除事实一开始就没存，不能证明真正删除或撤回传播成功 |

这不是“4 对 2 错”的准确率表：拒答、开放建议、删除能力和时间推理有不同成功条件；个别条件无法激活待测机制。审查由 Codex 对照可见输入、快照、结果和参考标注完成，未运行官方 judge。

## 时间失败还需要区分接口与方法

安装版本的 `Memory.add` 有 timestamp 参数，但 OSS 实现会在非空时直接拒绝；文档字符串注明是平台功能。因此本轮采用日期正文前缀，没有把原生 timestamp 调用假装成已测试。

保存的抽取提示中 Observation Date 与 Current Date 默认均为运行当天。这个默认值与回放旧历史不一致；正文前缀仅改善了其中一个日期。后续应单独验证事件时间的明确表示、写入后的日期审计，以及需要原文回溯的条件，而不是盲目增加 top-k。

## 本地产物与重新加载

全部原文、数据库和日志位于忽略的 `benchmark/data/runs/mem0-microstudy-20261007/`。`dataset-pack.json / plan.json / trace.jsonl / report.json` 固定输入与请求；`observability.jsonl` 连接模型调用、记忆快照和 Answer；`review.json` 保存本次定性审查与原文件哈希；`observations-reviewed.json` 将实际回答及审查投影接入展示。

```powershell
.\.venv\Scripts\python.exe -m visualization.build --local --web --run benchmark/data/runs/mem0-microstudy-20261007 --run-kind experiment --observations benchmark/data/runs/mem0-microstudy-20261007/observations-reviewed.json
```

这个命令只读已有产物，不重新调用模型。新实验另起 run，不覆盖这份记录。公开 `visualization/research.json` 仅保存审查摘要与来源哈希；原文和实际轨迹只进入本地扩展版。
