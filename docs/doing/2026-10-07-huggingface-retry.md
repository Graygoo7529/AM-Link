# Hugging Face 数据重试与核验

日期：2026-10-07。用户调整网络环境后，重新取得此前缺失的数据。所有原文、Parquet、pack 和 receipt 位于被 Git 忽略的 `dataset/data/`。

done：本轮保存 426 个文件，共 4,314,879,652 bytes（约 4.31 GB，不含 receipt/派生 pack）；最终逐文件重算 SHA-256、核对大小，400 个 PersonaMem-v2 历史引用全部存在。17 项数据测试、20 项 benchmark 测试、7 项可视化/案例测试及生成文件一致性检查通过。

## 已取得

- LongMemEval 固定 revision `98d7416`：S `277,383,467` bytes、M `2,737,100,077` bytes、Oracle `15,388,478` bytes；S/Oracle 均 500 题。S 为 23,867 sessions / 246,750 turns，Oracle 为 948 sessions / 10,960 turns；30 道 `_abs` 拒答题单独标记，可回答题 470 道。
- CL-bench `90,085,681` bytes、1,899 行；CL-bench Life `29,262,222` bytes、405 行。文件 SHA 与固定 revision receipt 一致。
- BEAM 常规 100K/500K/1M 三片共 90 rows、约 105.6 MB；BEAM-10M 两片共 10 rows、约 343.8 MB。Parquet 魔数、字段和逐批读取均通过。
- MemoryAgentBench 四类 Parquet：Accurate Retrieval 22 rows、Conflict Resolution 8 rows、Long Range Understanding 110 rows、Test Time Learning 6 rows；另有 `entity2id.json`，总数据约 76.6 MB。字段统一为 `context/questions/answers/metadata`，逐批读取通过。
- PersonaMem-v2：benchmark CSV 5,000 题、200 persona；题目引用的 32K/128K 历史共 400 份全部取得并逐文件校验。`persona 521` 已构建 188 turns / 3 tasks 的 32K smoke pack。
- PersonaMem-v3：公开 `samples/` 三表已取得并核对，100 profiles、221,817 events、15,791 queries。作者 README 明确三表覆盖这批人物的全部事件/问题；`backend/` 是原版评估器读取的另一种组织形式，本轮未下载。

## 处理产物

- `longmemeval-s-smoke.json`：6 题、299 sessions、3,159 turns。
- `longmemeval-oracle-smoke.json`：6 题、13 sessions、154 turns。
- `personamem-v2-persona521-smoke.json`：1 persona、188 turns、3 tasks；系统提示作为生成背景排除，不进入历史 Add，题目答案和偏好留在 annotations。
- LongMemEval S 中发现重复上游 session ID；读取器使用稳定的 `原 ID#2` pack ID，同时保留 `source_id`，避免破坏 pack 唯一性。此修复由测试覆盖。

## 仍未完整处理

- LongMemEval-M 已下载，但 2.74GB 只做文件和 JSON 流完整性核验，未构建全量 pack；后续应按题目/类型切片。
- BEAM、MemoryAgentBench 已下载但尚未转为中立 pack；Parquet 读取器还需要明确字段映射和许可边界。
- PersonaMem-v3 只取得公开预览表；后续按 persona 选择 `backend/{id}`，并遵守 query 时间遮罩，不能把未来事件写入历史。
- CL-bench 两个完整文件已取得，但当前 visualization 仍展示已有小样本 pack，未把完整文件直接混入运行分母。

本轮未调用模型、未启动服务、未修改远程数据；下载失败的 4 个 PersonaMem-v2 文件第一次遇到 TLS EOF，单独重试后全部成功。

核验时将 pyarrow 25.0.1 临时装入忽略的数据工具目录，逐批解码 9 个 Parquet 文件后移除；未修改项目虚拟环境或依赖配置。获取临时脚本已清理，各原文件的 `.receipt.json` 保留来源、版本、大小和 SHA-256。原有可视化/观测接口的未提交工作保留。
