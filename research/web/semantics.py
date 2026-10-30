"""Human-readable, bounded projections. Source text and labels remain unchanged."""
import ast
import json

FIELDS = {
    "text": "要交给方法的问题", "source_text": "原始容器写法", "prior_conversation": "提问前的当前对话",
    "answer": "作者参考答案", "answers": "作者可接受答案", "gold_answer": "作者参考答案",
    "evidence": "作者标记的证据位置", "evidence_turn_ids": "对应历史片段编号",
    "answer_session_ids": "作者标记的会话编号", "has_answer": "此片段是否被作者标为含答案",
    "rubrics": "逐项评分要求", "rubric": "评分要求", "category": "题目类别",
    "question_type": "题型", "metadata": "来源补充信息", "unanswerable": "是否标为不可回答",
    "role": "消息身份", "content": "说话内容", "user": "用户", "assistant": "助手",
    "event_id": "原始活动编号", "timestamp": "时间戳", "datetime": "原始日期时间",
    "app": "发生在哪个应用", "action": "实际动作", "user_message": "用户原话",
    "conversation_json": "活动内的对话", "title": "内容标题", "caption": "附文",
    "author": "内容作者", "recipient_id": "接收者编号", "is_dm": "是否私信",
    "is_ad": "是否广告", "is_trending": "是否热门", "media_description": "媒体描述",
    "audio_transcript": "音频转写", "location": "地点", "correct_answer": "作者参考选项",
    "options": "候选答案", "task_type": "任务类型", "preference": "作者偏好标注",
    "persona_id": "模拟人物编号", "sensitive": "敏感信息标签", "forget": "遗忘相关标签",
    "is_answerable": "作者是否认为历史足以回答", "reference_memory": "作者给出的参考记忆",
    "memory_anchors": "作者标记的原文锚点", "evidence_granularity": "证据定位的粒度",
    "anchor_offsets_verified": "锚点字符位置是否已核验", "ideal_answer": "作者期望的回答",
    "difficulty": "作者标注的难度", "update_type": "更新类型", "tests_retention_of": "测试保留哪类信息",
    "conversation_references": "关联的会话位置", "potential_confusion": "作者列出的易混淆点",
    "source_chat_ids": "来源会话编号", "contradiction_type": "矛盾类型", "topic_questioned": "问题主题",
    "tests_for": "作者希望测试的能力", "raw_persona_file": "生成背景文件位置（非可见历史）",
    "short_persona": "简要生成角色背景（仅研究侧）", "expanded_persona": "详细生成角色背景（仅研究侧）",
    "incorrect_answers": "作者提供的干扰答案", "topic_query": "问题主题标签", "topic_preference": "偏好主题标签",
    "conversation_scenario": "生成对话场景", "pref_type": "偏好类型标签", "related_conversation_snippet": "作者关联的对话片段",
    "who": "该信息属于谁", "updated": "是否标为偏好更新", "prev_pref": "此前偏好标签",
    "sensitive_info": "敏感信息标签", "what_this_tests": "此题要测什么", "groundtruth_preference": "作者参考偏好",
    "supporting_history": "作者列出的支持历史", "groundtruth_preference_obj": "参考偏好的结构化标注",
    "distractor_preferences": "干扰偏好", "golden_response": "作者理想回答", "inferior_response": "作者负面对照回答",
    "reference_example": "参考例子", "judge_prompt": "评分提示词（仅评估侧）", "tool_call": "作者标注的工具调用",
    "source_file": "原始来源文件", "content_type": "内容类型", "hashtags": "内容话题标签",
}
ENUMS = {"action": {"asked_to_forget": "请求遗忘", "liked": "点赞", "disliked": "不喜欢", "watched": "观看"},
    "app": {"Chatbot": "聊天助手"}, "who": {"user": "当前用户", "others": "其他人"}}
for window in ("32k", "128k"):
    FIELDS[f"total_tokens_in_chat_history_{window}"] = f"{window} 历史的 token 数（来源统计）"
    FIELDS[f"distance_from_related_snippet_to_query_{window}"] = f"{window} 历史中证据距提问的距离（来源口径）"
    FIELDS[f"num_persona_relevant_tokens_{window}"] = f"{window} 历史中角色相关 token 数"
    FIELDS[f"num_persona_irrelevant_tokens_{window}"] = f"{window} 历史中角色无关 token 数"


def decode(value):
    if isinstance(value, str) and len(value) < 100000 and value.lstrip().startswith(("{", "[")):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            try:
                result = ast.literal_eval(value)
                if isinstance(result, (dict, list)):
                    return result
            except (ValueError, SyntaxError, RecursionError):
                pass
    return value


def readable(value, *, max_rows=24, max_chars=700):
    rows, visited = [], 0
    def visit(obj, path, depth=0):
        nonlocal visited
        if len(rows) >= max_rows or visited > 300:
            return
        visited += 1
        obj = decode(obj)
        if isinstance(obj, dict) and depth < 4:
            for key, item in obj.items():
                visit(item, path+[str(key)], depth+1)
        elif isinstance(obj, list) and obj and depth < 4:
            if all(not isinstance(x, (dict, list)) for x in obj):
                leaf(obj, path)
            else:
                for i, item in enumerate(obj[:max_rows]):
                    visit(item, path+[str(i+1)], depth+1)
        else:
            leaf(obj, path)
    def leaf(obj, path):
        if obj is None:
            text = "未提供（null，不等于 false 或 0）"
        elif type(obj) is bool:
            text = "是（true）" if obj else "否（false）"
        elif isinstance(obj, str):
            text = FIELDS.get(obj, obj) if path and path[-1] == "role" else obj or "空字符串"
            translated = ENUMS.get(path[-1] if path else "", {}).get(obj)
            if translated:
                text = f"{translated}（{obj}）"
        elif isinstance(obj, list) and obj:
            text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(obj))
        else:
            text = json.dumps(obj, ensure_ascii=False)
        rows.append({"field": ".".join(path) or "content", "label": next((FIELDS[p] for p in reversed(path) if p in FIELDS), "说话内容" if not path else "来源字段（见原始字段解释）"),
            "value": text[:max_chars]+("…〔展示截断，完整内容见原文〕" if len(text)>max_chars else "")})
    visit(value, [])
    return rows
