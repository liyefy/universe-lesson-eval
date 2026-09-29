"""Validate/import human review decisions; never change findings or execute fixes."""
import argparse
from eval_contract import indexed, read_json, require, sha256, write_new

DECISIONS = {"unreviewed", "approve", "ignore", "defer"}


def validate_decisions(report_path, document):
    report = read_json(report_path)
    require(isinstance(report, dict) and report.get("version") == 2, "decisions require a v2 report")
    require(isinstance(document, dict), "decisions must be an object")
    require(type(document.get("version")) is int and document["version"] == 1, "decision version must be 1")
    for key in ("audit_id", "plan_sha256"):
        require(document.get(key) == report.get(key), f"decision {key} mismatch")
    require(document.get("report_sha256") == sha256(report_path), "decisions belong to a different report")
    issues = indexed(report.get("issues"), "report issues")
    decisions = indexed(document.get("decisions"), "decisions", "issue_id")
    require(set(decisions) == set(issues), "decision IDs must exactly cover report issues")
    for row in decisions.values():
        require(row.get("decision") in DECISIONS, "unknown review decision")
        require(isinstance(row.get("note"), str), "decision note must be text")
    return document


def initial_decisions(report_path):
    report = read_json(report_path)
    require(isinstance(report, dict) and report.get("version") == 2, "decisions require a v2 report")
    return {"version": 1, "audit_id": report["audit_id"], "plan_sha256": report["plan_sha256"],
            "report_sha256": sha256(report_path), "decisions": [
                {"issue_id": issue["id"], "decision": "unreviewed", "note": ""} for issue in report["issues"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        document = validate_decisions(args.report, read_json(args.input))
        write_new(args.out, document)
        print(f"Saved {len(document['decisions'])} decisions; no fixes or remote actions executed.")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(f"STOP: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
