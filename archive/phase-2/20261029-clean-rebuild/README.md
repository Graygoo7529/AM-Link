# 二期 r11 归档

2026-10-29开始，2026-10-30完成整理。这里保留归档时的未提交实现与设计，不仅是Git已提交版本。当前活动方法在根 amlink/，不要在这里继续实施。

- amlink-r11-unstable/：原实现、测试和README；与0.1.0归档不同。
- DESIGN-r11.md、README-r11.md：原设计入口。
- docs/doing、docs/phase-2：历史调研/执行计划/实验台账副本。
- AGENTS-r11.md：归档前项目记忆；AGENTS-transition.md是本次重构中途快照，含已过时的早期骨架状态。
- visualization-README-r11.md：清理前可视化说明。
- source-manifest.json：代码/设计内容的SHA-256清单（不包括运行数据）。

用户允许清除实验数据。本轮已清理旧benchmark runs/plans/research/研究环境及旧本地可视化数据，原始模型轨迹和实验库不承诺可恢复；历史结论保留在台账。原始数据集、prepared包、casestudies及一期归档保留。旧pytest缓存有Windows ACL拒绝访问残留，不作为活动实验库；不为删除缓存修改权限。

Git基线为60438c3；归档包含此前未提交的改动。未自动提交或部署。
