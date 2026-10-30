"""Publish aggregate research facts; source text and traces remain in ignored data/."""
from __future__ import annotations

import json
from pathlib import Path

from dataset.prepare import sha256_file

ROOT = Path(__file__).resolve().parents[1]
LABELS = {"single-session-user":"单会话·用户信息","single-session-assistant":"单会话·助手信息",
    "single-session-preference":"单会话·偏好","multi-session":"跨会话","temporal-reasoning":"时间推理","knowledge-update":"知识更新"}


def main():
    survey_path=ROOT/"dataset/data/research/survey.json"
    survey=json.loads(survey_path.read_text(encoding="utf-8")); s=survey["datasets"]
    lex_path=ROOT/"benchmark/data/research/lexical-longmem.json"
    lex=json.loads(lex_path.read_text(encoding="utf-8"))
    if lex["source_sha256"]!=s["longmem"]["sources"][0]["sha256"]: raise ValueError("survey/baseline source mismatch")
    ds={}
    def entry(key,purpose,counts,title,bars,note):
        ds[key]={"purpose":purpose,"counts":counts,"distribution":{"title":title,"values":list(bars.items())},"note":note}
    entry("longmem","区分找事实、收齐跨会话证据、解释时间、处理更新和拒答。",
        [["S 会话数中位数",s["longmem"]["sessions_per_question"]["median"]],["M 会话数中位数",s["longmem-m"]["sessions_per_question"]["median"]],
         ["Oracle 会话数中位数",s["longmem-oracle"]["sessions_per_question"]["median"]]],
        "500 道题的能力构成",{LABELS[k]:v for k,v in s["longmem"]["question_types"].items()},
        "其中 30 道是拒答题，跨题型分布；S/M/Oracle 是同题不同历史范围。54 个 has_answer 来源发言来自 assistant，不能统一丢弃助手信息。")
    entry("persona","检查个性化信息的归属、适用范围、遗忘与敏感信息。",
        [["题目",s["persona"]["tasks"]],["人物",s["persona"]["personas"]],["他人信息题",s["persona"]["labels"]["who"]["others"]]],
        "5,000 道题的 pref_type 标签",s["persona"]["labels"]["pref_type"],
        "who / updated / sensitive_info 是独立标注轴，不可相加；遗忘类 1,048，updated=True 1,047，不能互相替代。")
    for key,purpose in [("cl","把新规则、专业材料和流程用于完成工作。"),("life","从日志、多人讨论和信息修订中取得足够、合规的工作证据。")]:
        entry(key,purpose,[["任务",s[key]["tasks"]],["context 分组",s[key]["context_groups"]],["每题 rubric 中位数",s[key]["rubrics_per_task"]["median"]]],
              "按任务统计的内容类别",s[key]["categories"],
              "现有规则的边界识别："+"；".join(f"{k} {v}" for k,v in s[key]["boundaries"].items())+"。rubric 属于评分侧；一条历史消息可含大量评论或日志。")
    normal={k.split(":")[1]:v for k,v in s.items() if k.startswith("beam:")}
    large=[v for k,v in s.items() if k.startswith("beam-10m:")]
    entry("beam","在越来越长的聊天与代码中检查同类记忆能力。",
          [["常规历史",sum(v["histories"] for v in normal.values())],["10M 历史",sum(v["histories"] for v in large)],
           ["探针合计",sum(v["probes_per_history"]["sum"] for v in [*normal.values(),*large])]],"各规模实际题目数",
          {**{k:v["probes_per_history"]["sum"] for k,v in normal.items()},"10M":sum(v["probes_per_history"]["sum"] for v in large)},
          "每条历史都是 20 probes；规模增大主要拉长历史，不等于题目成比例增加。10M chat 的 plan/batch/turns 嵌套与常规档不同，不能复用浅层遍历。")
    mab={k:v for k,v in s.items() if k.startswith("memoryagentbench:")}
    entry("mab","覆盖普通检索、事实冲突、多跳、长摘要与从示例学习；评分必须按子任务区分。",
          [["context",sum(v["contexts"] for v in mab.values())],["问题",sum(v["questions_per_context"]["sum"] for v in mab.values())],["已适配研究问题",1]],"四类问题数",
          {k.split(":")[1]:v["questions_per_context"]["sum"] for k,v in mab.items()},
          "一个 context 对多题；电影推荐输出可能是实体 ID，长摘要有关键点。不能把四类合成一个字符串准确率。")
    entry("pv3","研究跨应用偏好、负反馈、时间遮罩、短期记忆和适度使用个性化。",
          [["人物",s["pv3"]["personas"]],["事件",s["pv3"]["events"]],["任务类型",len(s["pv3"]["task_types"])]],f'{s["pv3"]["events"]:,} 条事件的作者交互标签',
          s["pv3"]["interaction_types"],
          "共 15,791 queries；interaction_type 仅在此统计，Add 保留原动作；implicit_negative 不能直接当永久厌恶。推断标签、嵌套 embeds_pref_idx 和未来事件不进入 Add。")
    for key,profile in ds.items():
        if key in s: profile["sources"]=s[key]["sources"]
        elif key=="beam": profile["sources"]=[p for k,v in s.items() if k.startswith(("beam:","beam-10m:")) for p in v["sources"]]
        elif key=="mab": profile["sources"]=[p for v in mab.values() for p in v["sources"]]
    summary={"schema_version":1,"date":survey["date"],"survey_sha256":sha256_file(survey_path),"datasets":ds,
        "lexical":{"source_sha256":lex["source_sha256"],"artifact_sha256":sha256_file(lex_path),
            "method":lex["method"],"questions":lex["graded_questions"],"summary":lex["summary"],
            "by_type":lex["by_type"],"type_labels":LABELS,"limits":lex["limits"],
            "mab":{"top5_ids":[x["id"] for x in lex["mab_case"]["top5"]],"required_ids":lex["mab_case"]["manually_audited_path"]}},
        "checkpoints":[["输入","原文、角色、事件时间与独立限制是否完整；gold 是否隔离"],
            ["Add","每条派生记忆来自哪里；更新/撤回处理了哪个旧版本"],
            ["Search","找到了任一证据，还是收齐全部必要关系；缺的哪一跳"],
            ["上下文","哪些候选被保留或裁剪；日期、否定与来源有没有丢"],
            ["Answer / Eval","实际回答是否受证据支持；评分有没有混淆标注问题与方法问题"]]}
    run_dir=ROOT/"benchmark/data/runs/mem0-microstudy-20261007"
    if (run_dir/"review.json").exists():
        review=json.loads((run_dir/"review.json").read_text(encoding="utf-8"))
        for name,expected in review["artifacts"].items():
            if sha256_file(run_dir/name)!=expected: raise ValueError("microstudy review source mismatch")
        pack=json.loads((run_dir/"dataset-pack.json").read_text(encoding="utf-8"))
        attributes={r["id"]:r["attributes"] for r in pack["records"]}
        summary["microstudy"]={k:review[k] for k in ("run_id","reviewer","metric","calls","input_chars","cost_usd","limitations","artifacts")}
        summary["microstudy"]["review_sha256"]=sha256_file(run_dir/"review.json")
        summary["microstudy"]["cases"]=[{**r,"dataset_key":attributes[r["record_id"]]["dataset_key"]} for r in review["cases"]]
    output=ROOT/"visualization/research.json"
    output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(output)


if __name__=="__main__":main()
