"""Chinese Markdown report for one agent run."""
from datetime import datetime

SEVERITY = {"hard": "硬性不符", "soft": "需确认", "info": "提示"}
DECISION = {"reject": "筛掉", "review": "需人工确认", "pass": "通过", "error": "处理失败"}
VERDICT = {"direct": "直接支持", "related": "相关但不足", "insufficient": "证据不足", None: "处理失败"}
IMPORTANCE = {"required": "必需", "preferred": "优先", "unspecified": "未注明"}
CHANNEL = {"campus": "校招", "social": "社招", "unknown": "未识别"}


def _cell(text):
    return " ".join(str(text or "").split()).replace("|", "\\|")


def render(run_id, posting, screening, company, extraction, matches, summary, approved=None):
    lines = [f"# 匹配报告：{posting.get('title') or '未命名岗位'}", ""]
    meta = [
        ("公司", posting.get("company_name") or (company or {}).get("name") or "未填写"),
        ("城市", posting.get("city") or "未填写"),
        ("渠道", CHANNEL.get(posting.get("channel"), posting.get("channel"))),
        ("链接", posting.get("url") or "无"),
        ("运行编号", run_id),
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]
    lines += [f"- {k}：{v}" for k, v in meta] + [""]
    lines += ["> 证据覆盖分数只说明经历库里找到了多少证据，不是录用概率；证据不足不代表你不具备该能力。", ""]

    decision = screening.get("decision")
    lines += ["## 结论", ""]
    review_note = ""
    if decision == "review" and approved is not None:
        review_note = "（你已确认继续）" if approved else "（你选择不继续）"
    lines.append(f"- 筛选：{DECISION.get(decision, decision)}{review_note}")
    if summary:
        score = "无法评分" if summary.get("score") is None else f"{summary['score']} 分（{summary['label']}）"
        lines.append(f"- 证据覆盖：{score}")
        lines.append(f"- 必需条件有证据：{summary['required_covered']}/{summary['required_total']}")
        c = summary["counts"]
        lines.append(f"- 逐条结果：直接支持 {c['direct']}，相关 {c['related']}，证据不足 {c['insufficient']}，"
                     f"处理失败 {c['error']}")
    lines.append("")

    flags = screening.get("flags", [])
    lines += ["## 筛选结果", ""]
    if flags:
        lines += ["| 级别 | 项目 | 说明 | JD 原文 |", "| --- | --- | --- | --- |"]
        for f in flags:
            lines.append(f"| {SEVERITY[f['severity']]} | {f['code']} | {_cell(f['message'])} | {_cell(f['quote'])} |")
    else:
        lines.append("没有发现需要注意的条件。")
    lines.append("")

    if company:
        lines += [f"## 企业：{company['name']}", ""]
        for p in company.get("programs", []):
            lines.append(f"- {p['title']}：{p['verdict_label']}。{p['verdict_reason']}"
                         + (f"；状态：{p['status_text']}" if p.get("status_text") else ""))
        lines.append("")

    screened = [r for r in (extraction or {}).get("requirements", []) if r.get("category") == "location"]
    if screened:
        lines += ["## 由筛选处理的要求", "", "工作地点类要求不做证据匹配，见上面筛选结果里的城市判断：", ""]
        lines += [f"- {r['requirement_id']} {r['text']}（JD 原文：{_cell(r.get('source_quote'))}）" for r in screened]
        lines.append("")

    if matches:
        lines += ["## 逐条要求", ""]
        for m in sorted(matches, key=lambda m: m["requirement_id"]):
            lines.append(f"### {m['requirement_id']} [{IMPORTANCE.get(m['importance'], m['importance'])}] "
                         f"{m['text']} — {VERDICT.get(m.get('verdict'), m.get('verdict'))}")
            lines.append("")
            if m.get("source_quote"):
                lines.append(f"JD 原文：{_cell(m['source_quote'])}")
                lines.append("")
            if m.get("reason"):
                lines.append(f"理由：{m['reason']}")
                lines.append("")
            for e in m.get("evidence", []):
                lines.append(f"> {_cell(e['quote'])}")
                lines.append(f"> — {e['project']} / {e['section']}（{e['source']}:{e['line_start']}-{e['line_end']}）")
                lines.append("")
            if m.get("missing_aspects"):
                lines.append("未覆盖：" + "；".join(m["missing_aspects"]))
                lines.append("")
            if m.get("questions_for_user"):
                lines.append("可以向你确认：" + "；".join(m["questions_for_user"]))
                lines.append("")
            if m.get("errors"):
                lines.append("处理提示：" + "；".join(m["errors"]))
                lines.append("")

        gaps = [m for m in matches if m.get("verdict") == "insufficient" and m["importance"] != "preferred"
                and m["category"] != "responsibility"]
        lines += ["## 证据缺口", ""]
        lines += [f"- {m['requirement_id']} {m['text']}" for m in gaps] or ["- 入职条件都找到了至少部分证据。"]
        lines.append("")

    notes = (extraction or {}).get("warnings", []) + [
        f"第 {b['index']}/{b['count']} 批（第 {b['line_start']}-{b['line_end']} 行）提取失败：{b['message']}"
        for b in (extraction or {}).get("failed_batches", [])]
    if notes:
        lines += ["## 提取说明", ""] + [f"- {n}" for n in notes] + [""]
    if summary:
        lines += [f"评分方法：{summary['formula']}。", ""]
    return "\n".join(lines)
