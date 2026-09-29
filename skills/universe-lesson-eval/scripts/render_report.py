"""Render gate-derived Markdown and a local HTML review page from a v2 report."""
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote
from eval_contract import indexed, read_json, require, write_new
from report_gate import validate
from review_decisions import initial_decisions, validate_decisions

DIMENSIONS = {"science": "科学与文案", "interaction": "交互与引导", "motion": "动画与媒体",
              "viewport": "视口与排版", "hypothesis": "假设与闭环"}
STATUS = {"pass": "通过", "fail": "已确认缺陷", "unverified": "未验证", "not_applicable": "不适用"}
SEVERITY = {"severe": "严重", "moderate": "中度", "minor": "轻微"}


def escaped(value):
    return html.escape(str(value), quote=True)


def md_text(value):
    return str(value).replace("\\", "\\\\").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]").replace("<", "&lt;").replace("|", "\\|").replace("\n", " ")


def media(evidence, report_root, output_root):
    path = (report_root / evidence["path"]).resolve()
    absolute = path.as_posix()
    relative = quote(os.path.relpath(path, output_root).replace("\\", "/"), safe="/:")
    label = evidence["observation"]
    suffix = path.suffix.lower()
    link = f'<a href="{escaped(relative)}">{escaped(label)}</a>'
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return f"![{md_text(label)}](<{absolute}>)", f'<figure><img loading="lazy" src="{escaped(relative)}" alt="{escaped(label)}"><figcaption>{escaped(label)}</figcaption></figure>'
    if suffix in {".mp4", ".webm"}:
        return f"[{md_text(label)}](<{absolute}>)", f'<video controls preload="metadata" src="{escaped(relative)}"></video><p>{escaped(label)}</p>'
    if suffix in {".mp3", ".wav", ".ogg", ".m4a"}:
        return f"[{md_text(label)}](<{absolute}>)", f'<audio controls preload="metadata" src="{escaped(relative)}"></audio><p>{escaped(label)}</p>'
    return f"[{md_text(label)}](<{absolute}>)", f'<p>{link}</p>'


def location(issue):
    value = issue.get("code_location")
    if not isinstance(value, dict):
        return "", ""
    path, line = value.get("path"), value.get("line")
    require(isinstance(path, str) and Path(path).is_absolute() and Path(path).is_file(),
            "code_location must name an existing absolute source file")
    require(type(line) is int and 1 <= line <= len(Path(path).read_text(encoding="utf-8-sig").splitlines()),
            "code_location line must exist")
    target = Path(path).as_posix() + f":{line}"
    extra = " · ".join(str(value[key]) for key in ("component", "state") if value.get(key))
    return (f"源码：[{md_text(Path(path).name)}](<{target}>) {md_text(extra)}",
            f'<p>源码：<code>{escaped(target)}</code> {escaped(extra)}</p>')


def render(plan_path, report_path, lock_path, output_dir, decisions_path=None):
    checked = validate(plan_path, report_path, lock_path)
    require(checked["valid"], "report gate rejected: " + "; ".join(checked["errors"]))
    report, plan = read_json(report_path), read_json(plan_path)
    require(report.get("version") == 2, "rendering requires v2; legacy reports have no comparable score")
    decisions = (validate_decisions(report_path, read_json(decisions_path)) if decisions_path
                 else initial_decisions(report_path))
    out, report_root = Path(output_dir).resolve(), Path(report_path).resolve().parent
    names = ["report.md", "report.html", "gate-result.json", "review-decisions.json"]
    require(all(not (out / name).exists() for name in names), "report output exists; choose a fresh directory")
    score, counts = checked["score"], checked["counts"]
    scope = "整课范围" if plan["scope"]["coverage"] == "full" else "指定局部范围"
    score_label = (("暂无可评分证据" if score["provisional"] else "无适用评分项")
                   if score["value"] is None else f"{'暂计 ' if score['provisional'] else ''}{score['value']} / 100")
    grade = score.get("grade") or "未评级"
    hard = checked["hard_findings"]
    hard_label = f"含 {len(hard)} 处硬伤" if hard else "已确认严重问题 0 项"
    title = plan["scope"]["topic"]
    summary = f"{score_label} · {grade} · {hard_label}"
    coverage = " ｜ ".join(f"{STATUS[key]} {counts[key]}" for key in STATUS)
    md = [f"# 验收报告：{md_text(title)}", "", f"**{summary}**", "", f"{scope} · {md_text(plan['scope']['version'])}", "", coverage,
          "", "评分仅描述冻结范围内的质量；未验证项不作为通过，评级不代表发布授权。", ""]
    cards = []
    dimension_items = []
    for dimension, data in score["dimensions"].items():
        coverage_row = checked["coverage"]["by_dimension"][dimension]
        if not data["active"]:
            value = "不适用"
        elif not (coverage_row["pass"] + coverage_row["fail"]):
            value = f"未验证（预算 {data['budget']}）"
        else:
            value = f"{'暂计 ' if coverage_row['unverified'] else ''}{data['earned']} / {data['budget']}"
        md.append(f"- {DIMENSIONS[dimension]}：{value}（原始扣分 {data['raw_deduction']}，实际扣分 {data['applied_deduction']}）")
        dimension_items.append(f'<li>{escaped(DIMENSIONS[dimension])}：{escaped(value)}'
            f' · 原始扣分 {escaped(data["raw_deduction"])}，实际扣分 {escaped(data["applied_deduction"])}</li>')
    dimension_html = "".join(dimension_items)
    rows = indexed(report["results"], "results")
    case_map = indexed(plan["cases"], "cases")
    deductions = {item["issue_id"]: item for item in score["deductions"]}
    decision_map = {row["issue_id"]: row for row in decisions["decisions"]}
    for issue in report["issues"]:
        item = deductions[issue["id"]]
        heading = f"{issue['id']} · {issue['summary']}"
        detail = f"{SEVERITY[issue['severity']]} · 原始扣分 {item['raw']} · 实际扣分 {item['applied']}"
        md.extend(["", f"## {md_text(heading)}", "", detail, "", f"实际：{md_text(issue['actual'])}", "",
                   f"预期：{md_text(issue['expected'])}", "", f"影响：{md_text(issue['impact'])}", "",
                   f"覆盖：{', '.join(issue['case_ids'])}", ""])
        fragments, seen = [], set()
        for case_id in issue["case_ids"]:
            for evidence in rows[case_id]["evidence"]:
                if evidence["path"] in seen:
                    continue
                seen.add(evidence["path"])
                markdown, fragment = media(evidence, report_root, out)
                md.extend([markdown, ""])
                fragments.append(fragment)
        review = issue["review"]
        review_label = "同一检查独立重跑" if review["method"] == "rerun" else "不同执行者独立复核"
        md.extend([f"复核：{review_label} · {md_text(review['reviewer'])}；{md_text(review['reason'])}", ""])
        review_fragments = []
        for evidence in review["evidence"]:
            markdown, fragment = media(evidence, report_root, out)
            md.extend([markdown, ""])
            review_fragments.append(fragment)
        review_html = (f'<details><summary>复核证据 · {escaped(review_label)}</summary>'
                       f'<p>{escaped(review["reviewer"])}：{escaped(review["reason"])}</p>'
                       + "".join(review_fragments) + '</details>')
        loc_md, loc_html = location(issue)
        if loc_md:
            md.extend([loc_md, ""])
        suggestion = issue.get("suggestion", "")
        if suggestion:
            md.extend([f"最小修改建议：{md_text(suggestion)}", ""])
        decision = decision_map[issue["id"]]
        md.append(f"批阅：{decision['decision']}；备注：{md_text(decision['note'])}。使用 HTML 页面保存/导出批阅。")
        options = "".join(f'<option value="{key}"{" selected" if decision["decision"] == key else ""}>{label}</option>'
                          for key, label in (("unreviewed", "未批阅"), ("approve", "确认修改"), ("ignore", "忽略不改"), ("defer", "暂缓")))
        cards.append(f'<article data-issue="{escaped(issue["id"])}"><h2>{escaped(heading)}</h2><p class="severity">{escaped(detail)}</p>'
                     f'<p><b>实际：</b>{escaped(issue["actual"])}</p><p><b>预期：</b>{escaped(issue["expected"])}</p>'
                     f'<p><b>影响：</b>{escaped(issue["impact"])}</p><p>覆盖：{escaped(", ".join(issue["case_ids"]))}</p>'
                     + "".join(fragments) + review_html + loc_html + (f'<p>最小修改建议：{escaped(suggestion)}</p>' if suggestion else "")
                     + f'<label>批阅 <select aria-label="{escaped(issue["id"])} 批阅">{options}</select></label>'
                     f'<label>备注 <textarea aria-label="{escaped(issue["id"])} 备注">{escaped(decision["note"])}</textarea></label></article>')
    md.extend(["", "## 完整检查记录", "", "| 检查 | 结论 | 说明 |", "| --- | --- | --- |"])
    table = []
    for row in report["results"]:
        label = f"{row['id']} · {case_map[row['id']]['title']}"
        md.append(f"| {md_text(label)} | {STATUS[row['status']]} | {md_text(row['reason'])} |")
        evidence_links = " ".join(media(e, report_root, out)[1] for e in row["evidence"])
        table.append(f'<tr><td>{escaped(label)}</td><td>{STATUS[row["status"]]}</td><td>{escaped(row["reason"])} {evidence_links}</td></tr>')
    assets = Path(__file__).resolve().parents[1] / "assets"
    template = (assets / "report.html").read_text(encoding="utf-8")
    context = {"TITLE": escaped(title), "SUMMARY": escaped(summary), "SCOPE": escaped(scope),
               "COVERAGE": escaped(coverage), "DIMENSIONS": dimension_html, "CARDS": "".join(cards) or "<p>无已确认缺陷。</p>",
               "ROWS": "".join(table), "DATA": json.dumps(decisions, ensure_ascii=False).replace("<", "\\u003c"),
               "SCRIPT": (assets / "report.js").read_text(encoding="utf-8")}
    # Replace placeholders in one pass; untrusted report content is never interpreted as a template.
    import re
    page = re.sub(r"@@([A-Z]+)@@", lambda match: context[match[1]], template)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "report.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(md) + "\n")
    with (out / "report.html").open("x", encoding="utf-8") as stream:
        stream.write(page)
    write_new(out / "gate-result.json", checked)
    write_new(out / "review-decisions.json", decisions)
    return {"markdown": str(out / "report.md"), "html": str(out / "report.html"), "complete": checked["complete"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("plan", "report", "lock", "output-dir"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--decisions")
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.plan, args.report, args.lock, args.output_dir, args.decisions), ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"STOP: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
