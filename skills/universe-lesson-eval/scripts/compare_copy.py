"""Exact copy comparison with contextual term and rhythm candidates.
Differences are candidates, never scientific verdicts."""
import argparse
from difflib import SequenceMatcher
import json
import re
from eval_contract import indexed, read_json, require, text_fields, write_new

PAUSE_PUNCTUATION_PATTERN = re.compile(r"[，,；;：:、——\n\r。？！?!…~]+")
DEFAULT_PROHIBITED_TERMS = [
    "三体运动",
    "三体问题",
    "降维打击",
    "引力透镜",
    "磁重联",
    "奇点",
]


def normalize(text, layout_whitespace):
    # Preserve word/number boundaries. Never remove all whitespace or punctuation.
    return re.sub(r"[ \t\r\n\f\v\u00a0\u3000]+", " ", text).strip() if layout_whitespace else text


def analyze_text_rhythm(text, max_clause_length=18):
    """Analyze breathing rhythm and clause lengths.
    Flags clauses exceeding max_clause_length without pause punctuation."""
    require(type(max_clause_length) is int and max_clause_length > 0,
            "max_clause_length must be a positive integer")
    if not text:
        return {"warnings": [], "max_clause_length": 0}
    clauses = [c.strip() for c in PAUSE_PUNCTUATION_PATTERN.split(text) if c.strip()]
    warnings = []
    max_len = 0
    for clause in clauses:
        clean_len = len(re.sub(r"\s+", "", clause))
        if clean_len > max_len:
            max_len = clean_len
        if clean_len > max_clause_length:
            warnings.append({
                "clause": clause,
                "length": clean_len,
                "limit": max_clause_length,
                "candidate_only": True,
                "warning": f"子句共 {clean_len} 字，超过本次扫描参考值 {max_clause_length}；须核对语言规范适用范围"
            })
    return {"warnings": warnings, "max_clause_length": max_len}


def term_list(value, label):
    require(isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value),
            f"{label} must be an array of nonempty strings")
    require(len(value) == len(set(value)), f"{label} must not contain duplicates")
    return value


def detect_prohibited_terms(text, terms=None, approved_terms=None):
    """Return review candidates; a literal match cannot establish curriculum scope."""
    terms_to_check = term_list(terms if terms is not None else DEFAULT_PROHIBITED_TERMS, "terms")
    approved = set(term_list(approved_terms if approved_terms is not None else [], "approved_terms"))
    if not text:
        return []
    detected = []
    for term in terms_to_check:
        if term in text and term not in approved:
            detected.append({
                "term": term,
                "candidate_only": True,
                "warning": f"术语候选：'{term}'；须结合已确认原文、年级、术语表与教学角色判断，不自动判违规"
            })
    return detected


def compare(data, layout_whitespace=False, prohibited_terms=None, max_clause_length=18):
    require(isinstance(data, dict) and type(data.get("version")) is int and data["version"] == 1,
            "input version must be integer 1")
    rows = indexed(data.get("comparisons"), "comparisons")
    require(rows, "comparisons cannot be empty")
    custom_terms = data.get("prohibited_terms", prohibited_terms)
    approved_terms = term_list(data.get("approved_terms", []), "approved_terms")
    output = []
    for case_id, row in rows.items():
        text_fields(row.get("source"), ["anchor", "paragraph"], case_id)
        text_fields(row, ["expected", "actual_origin"], case_id)
        require(isinstance(row.get("actual"), str), f"{case_id}: actual must be text (empty is allowed)")
        expected, actual = (normalize(row[key], layout_whitespace) for key in ("expected", "actual"))
        differences = [{"operation": tag, "expected_span": [i, j], "actual_span": [k, l],
                        "expected": expected[i:j], "actual": actual[k:l]}
                       for tag, i, j, k, l in SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes()
                       if tag != "equal"]

        target_text = actual
        rhythm_info = analyze_text_rhythm(target_text, max_clause_length)
        local_approved = term_list(row.get("approved_terms", []), f"{case_id}.approved_terms")
        term_info = detect_prohibited_terms(target_text, custom_terms, list(set(approved_terms + local_approved)))
        for item in term_info:
            item["present_in_expected"] = item["term"] in expected

        metrics = {
            "breath_rhythm_warnings": rhythm_info["warnings"],
            "max_clause_length": rhythm_info["max_clause_length"],
            "prohibited_term_warnings": term_info,
        }

        output.append({**row, "comparison": "candidate_difference" if differences else "match",
                       "differences": differences, "metrics": metrics})
    return {"version": 1, "scope": "copy_only", "layout_whitespace": layout_whitespace,
            "runtime_verified": False, "comparisons": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--layout-whitespace", action="store_true")
    parser.add_argument("--max-clause-length", type=int, default=18,
                        help="advisory clause length for this source policy (default: 18)")
    parser.add_argument("--prohibited-terms", help="comma-separated list of prohibited terms")
    parser.add_argument("--out", help="optional new JSON output; refuses overwrite")
    args = parser.parse_args()
    terms = [t.strip() for t in args.prohibited_terms.split(",") if t.strip()] if args.prohibited_terms else None
    try:
        result = compare(read_json(args.input), args.layout_whitespace,
                         prohibited_terms=terms, max_clause_length=args.max_clause_length)
        if args.out:
            write_new(args.out, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(any(row["differences"] for row in result["comparisons"]))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
