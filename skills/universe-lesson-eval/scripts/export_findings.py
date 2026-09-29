"""Export reviewed product failures for the existing Feishu writer; never access Feishu."""
import argparse
import json
import re
import sys
from pathlib import Path

from report_gate import validate
from eval_contract import read_json
from review_decisions import validate_decisions


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty text required")
    return value.strip()


def validate_export(document):
    """Validate the portable handoff format without importing an external writer."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", document["audit_id"]):
        raise ValueError("audit_id must be a stable ASCII task identifier.")
    seen = set()
    for row in document["findings"]:
        key = row["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", key) or key in seen:
            raise ValueError("Finding IDs must be unique ASCII identifiers.")
        seen.add(key)
        problem = row["problem"]
        if len(problem) > 60 or "\n" in problem or "\r" in problem:
            raise ValueError(f"{key}: problem must be one short line, at most 60 characters.")
        nonempty(row["description"], f"{key}.description")
        if row["certainty"] != "confirmed":
            raise ValueError(f"{key}: only confirmed findings may be exported.")


def export_findings(plan_path, report_path, lock_path, decisions_path=None):
    result = validate(plan_path, report_path, lock_path)
    if not result["valid"]:
        raise ValueError("Report gate rejected: " + "; ".join(result["errors"]))
    report_path = Path(report_path)
    report = read_json(report_path)
    modern = report["version"] == 2
    decisions = None
    if decisions_path:
        if not modern:
            raise ValueError("Review decisions require v2")
        decisions = {row["issue_id"]: row["decision"] for row in
                     validate_decisions(report_path, read_json(decisions_path))["decisions"]}
    root = report_path.parent.resolve()
    rows, warnings = [], []
    seen_problems, seen_records = set(), set()
    candidates = ([{"id": issue["id"], "status": "fail", "finding": issue} for issue in report["issues"]]
                  if modern else report["results"])
    for case in candidates:
        finding = case.get("finding")
        if case["status"] != "fail" or not isinstance(finding, dict):
            continue
        if finding.get("kind") != "product" or finding.get("certainty") != "confirmed":
            warnings.append(f"{case['id']}: unconfirmed or non-product finding kept local")
            continue
        key = case["id"]
        if decisions is not None and decisions[key] != "approve":
            warnings.append(f"{key}: not approved in supplied decisions; kept local")
            continue
        fields = {name: nonempty(finding.get(name), f"{key}.{name}") for name in (
            "summary", "location", "environment", "actual", "expected", "impact",
            "evidence_summary", "boundary")}
        steps = finding.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{key}: reproduction steps required")
        steps = [nonempty(step, f"{key}.steps") for step in steps]
        review = finding.get("review")
        if not isinstance(review, dict) or review.get("confirmed") is not True:
            raise ValueError(f"{key}: independent confirmed review required")
        reviewer = nonempty(review.get("reviewer"), f"{key}.reviewer")
        nonempty(review.get("reason"), f"{key}.review.reason")
        if not modern:
            executor = nonempty(case.get("executor") or report.get("executor"), f"{key}.executor")
            executors = {executor.casefold(), str(report.get("executor", "")).strip().casefold()}
            executors.update(str(e.get("executor", "")).strip().casefold() for e in case["evidence"])
            if reviewer.casefold() in executors:
                raise ValueError(f"{key}: reviewer must be independent of executors")
            evidence = review.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError(f"{key}: review evidence required")
            for item in evidence:
                path = (root / nonempty(item, f"{key}.review.evidence")).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
                    raise ValueError(f"{key}: review evidence must be a nonempty file inside report directory")
        topic = finding.get("topic")
        if topic is not None:
            nonempty(topic, f"{key}.topic")
        description = "\n".join([
            ("来源：自动化验收，已独立重跑；仅登记问题，尚未修复。" if modern and review["method"] == "rerun"
             else "来源：AI 验收，已独立复核；仅登记问题，尚未修复。"),
            "位置：" + fields["location"], "环境与版本：" + fields["environment"],
            "操作：" + " → ".join(steps), "实际：" + fields["actual"],
            "预期：" + fields["expected"], "影响：" + fields["impact"],
            "证据：" + fields["evidence_summary"], "验证边界：" + fields["boundary"],
        ])
        row = {"id": key, "topic": topic, "problem": fields["summary"],
               "certainty": "confirmed", "description": description}
        if "record_id" in finding:
            row["record_id"] = nonempty(finding["record_id"], f"{key}.record_id")
        jargon = r"\b(?:DOM|useFrame|Zustand|Canvas|P[0-3]|AGENTS\.md)\b|src[/\\]|\w+\.(?:tsx?|jsx?)\b"
        if re.search(jargon, fields["summary"] + "\n" + description, re.I):
            warnings.append(f"{key}: possible engineering wording; writer must review human readability")
        signature = (topic or "", re.sub(r"\s+", " ", fields["summary"]).casefold())
        record_id = row.get("record_id")
        if signature in seen_problems or (record_id and record_id in seen_records):
            raise ValueError(f"{key}: duplicate finding; review/merge and preserve related cases locally")
        seen_problems.add(signature)
        if record_id:
            seen_records.add(record_id)
        rows.append(row)
    document = {"audit_id": report["audit_id"], "findings": rows}
    validate_export(document)
    return document, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("plan", "report", "lock", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--decisions", type=Path, help="optional human decisions; export approved issues only")
    args = parser.parse_args()
    document, warnings = export_findings(args.plan, args.report, args.lock, args.decisions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"exported": len(document["findings"]), "warnings": warnings,
                      "output": str(args.output), "written_to_feishu": False}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(2)
