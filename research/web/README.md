# 唯一研究页面

入口是 [research/data/index.html](../data/index.html)，在根目录运行 `python -m research.web.build` 重建。不再生成独立案例页、会话页或百题页。

页面模板 `page.html`；构建器 `build.py`；数据语义与绑定 `profiles.json`；可读字段 `semantics.py`；数据身份与原文读取 `sources.py`；轨迹/材料校验 `traces.py`、`spans.py`。`bundle.py` 保留共享数据组装与旧观测兼容读取，不另生成页面。

案例唯一来源为 `research/cases/catalog.json`；活动运行登记由 `research.benchmark.workspace` 管理；批次汇总配置为 `research/workspace.json`。图表中的原始规模、当前准备包规模和本轮测试规模分别标注。

构建先验数据/计划/轨迹/步骤身份及哈希，再写按运行加载的JS分片。正文通过安全文本渲染，生成数据转义script边界，无远程脚本、字体、请求或模型调用。向量值投影为维数；完整原始材料链接保留。完整文本按步骤加载并可滚动，不以首尾摘要冒充完整模型输入。

展示是本地实验数据，不能将整个 `data` 文件夹当公共网站发布。普通浏览器可直接打开；Codex访问仍受连接器权限约束。详见[研究入口](../README.md)及[设计](DESIGN.md)。
