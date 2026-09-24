"""Account-scoped, deterministic projection of reviewed synthetic tool outputs.

No model prose is parsed. Frozen fixture equality bounds both provenance and
public fields; this adapter is deliberately not a generic raw-output endpoint.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = json.loads(Path(__file__).with_name("scenario_data.json").read_text())
CONTEXT = "peixian_get_scenario_context"
LABELS = {"night": "夜间观测", "portrait": "同框与同行记录", "funds": "原始资金流水", "lookup": "明确对应关系", "vehicle": "车辆使用记录", "calls": "通话记录", "composite": "既有关系引用"}
TOOLS = {"peixian_get_" + m + "_records": m for m in LABELS}
FIELDS = {"record_id": "记录编号", "occurred_at": "观测时间", "member_ref": "对象引用", "group_ref": "归属引用", "counterparty_ref": "对手账户", "co_member_ref": "共同出现对象", "amount_minor": "金额（分）", "direction": "方向", "kind": "记录类型", "device_ref": "设备引用", "passage_ref": "通行编号", "transaction_ref": "流水编号"}


def permitted(store, uid):
    with store.read(snapshot=True) as db:
        row = db.execute("SELECT applied_spec_ciphertext FROM runtimes WHERE uid=?", (uid,)).fetchone()
        grant = db.execute("SELECT 1 FROM grants WHERE uid=? AND kind='plugin' AND resource='peixian-synthetic-records'", (uid,)).fetchone()
        applied = store.decrypt(row[0]) if row and row[0] else {}
    plugins = applied.get("plugins", [])
    matches = [p for p in plugins if p.get("id") == "peixian-synthetic-records" and p.get("manifest", {}).get("version") in ("1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.1")]
    # Another plugin claiming these names must not acquire this public projection.
    if not grant or len(matches) != 1:
        return False
    names = set(TOOLS) | {CONTEXT, "peixian_prepare_scenario_facts", "peixian_check_scenario_summary"}
    return not any(names.intersection(p.get("manifest", {}).get("tools", [])) for p in plugins if p is not matches[0])


def night(value):
    local = datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8)))
    return local.hour >= 22 or local.hour < 6


def project(messages, authorized):
    result = {"schema_version": "1", "status": "empty", "scenario": None, "steps": [], "cards": [], "missing": [], "summary": [], "notice": "仅整理已有记录。"}
    if not authorized:
        return result
    starts = [i for i, m in enumerate(messages) if m.get("info", {}).get("role") == "user"]
    if not starts:
        return result
    result["turn_id"] = messages[starts[-1]].get("info", {}).get("id", "")
    turn = messages[starts[-1] + 1:]
    from .scenario_facts import project_facts
    computed = project_facts(turn, result, DATA)
    if computed is not None:
        return computed
    accepted = {}
    context = None
    for message in turn:
        if message.get("info", {}).get("role") != "assistant":
            continue
        for part in message.get("parts", []):
            tool = part.get("tool")
            if part.get("type") != "tool" or tool not in {*TOOLS, CONTEXT}:
                continue
            state = part.get("state", {})
            status = state.get("status", "pending")
            step = {"label": "场景上下文" if tool == CONTEXT else LABELS[TOOLS[tool]], "status": status if status in ("pending", "running", "completed", "error") else "pending"}
            result["steps"].append(step)
            if status != "completed":
                continue
            try:
                raw = state.get("output", "")
                if not isinstance(raw, str) or len(raw) > 1048576:
                    raise ValueError()
                output = json.loads(raw)
                if tool == CONTEXT:
                    sid = state.get("input", {}).get("scenario_id")
                    expected = DATA["scenarios"].get(sid)
                    if expected is None or state.get("input") != {"scenario_id": sid} or output != expected:
                        raise ValueError()
                    if context is not None and context != expected:
                        # Multiple scenario contexts in one turn cannot be mixed.
                        return {**result, "status": "unavailable", "cards": [], "missing": ["本轮包含多个场景，请新建对话分别核对。"]}
                    context = expected
                else:
                    module = TOOLS[tool]
                    expected = DATA["records"][module]
                    fields = ["module", "synthetic", "snapshot_id", "data_status", "returned_count", "total_count", "has_more", "rule_version", "rule_status"]
                    if state.get("input") != {} or any(type(output.get(k)) is not type(expected[k]) or output.get(k) != expected[k] for k in fields) or output.get("items") != expected["records"]:
                        raise ValueError()
                    accepted[module] = (expected["records"], message["info"].get("id", ""))
            except (ValueError, TypeError, KeyError, AttributeError):
                step["status"] = "error"
                result["missing"].append(step["label"] + "的输出未通过固定资料版本检查。")
    if context is None:
        if result["steps"]:
            result["status"] = "partial"
            result["missing"].append("尚未取得有效场景上下文，不生成事实卡片。")
        return result
    result["scenario"] = {k: context[k] for k in ("scenario_id", "title", "subject_ref", "snapshot_id", "records_snapshot_id", "rule_version", "timezone", "night_window", "case_window")}
    result["missing"].extend(context["limitations"])
    available_ids = {row["record_id"] for rows, _ in accepted.values() for row in rows}
    for fact in context["facts"]:
        if not set(fact["source_record_ids"]) <= available_ids:
            result["missing"].append(fact["title"] + "：尚未取得其引用的原始资料。")
            continue
        result["cards"].append({"id": fact["record_id"], "title": fact["title"], "description": fact["description"], "time": fact["occurred_at"], "source_ids": fact["source_record_ids"] + ([fact["source_document"]] if fact.get("source_document") else []), "fields": [], "message_id": "", "snapshot_id": context["snapshot_id"]})
    subject = context["subject_ref"]
    for module in context["required_modules"]:
        if module not in accepted:
            result["missing"].append(LABELS[module] + "尚未完成获取。")
            continue
        rows, mid = accepted[module]
        rows = [row for row in rows if subject in (row.get("group_ref"), row.get("member_ref"), row.get("co_member_ref"))]
        dates = sorted({row["occurred_at"][:10] for row in rows if row.get("occurred_at")})
        result["summary"].append({"label": LABELS[module], "count": len(rows), "dates": dates, "night_count": sum(night(row["occurred_at"]) for row in rows if row.get("occurred_at"))})
        for row in rows:
            fields = [{"label": label, "value": str(row[key])} for key, label in FIELDS.items() if key in row]
            result["cards"].append({"id": row["record_id"], "title": LABELS[module], "description": "来源记录的直接摘录；不代表行为目的或违法犯罪结论。", "time": row.get("occurred_at", ""), "source_ids": row.get("source_record_ids", []), "fields": fields, "message_id": mid, "snapshot_id": context["records_snapshot_id"]})
    result["cards"].sort(key=lambda x: (x["time"], x["id"]))
    result["status"] = "complete" if all(m in accepted for m in context["required_modules"]) and all(s["status"] == "completed" for s in result["steps"]) else "partial"
    return result
