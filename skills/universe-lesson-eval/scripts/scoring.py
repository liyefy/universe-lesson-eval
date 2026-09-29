"""Pure deterministic v2 scoring of already validated and reviewed issues."""

DIMENSION_BUDGETS = {"science": 30, "interaction": 25, "motion": 20, "viewport": 15, "hypothesis": 10}
SEVERITY_DEDUCTIONS = {"severe": 20, "moderate": 7, "minor": 2}


def unavailable_score(scope=None):
    return {"value": None, "grade": None, "provisional": True, "scope": scope,
            "active_budget": 0, "dimensions": {}, "deductions": []}


def derive_score(plan, results, issues):
    dimensions = {}
    for name, budget in DIMENSION_BUDGETS.items():
        if name not in plan["scope"]["dimensions"]:
            continue
        case_ids = [case["id"] for case in plan["cases"] if case["dimension"] == name]
        active = any(results[case_id]["status"] != "not_applicable" for case_id in case_ids)
        dimensions[name] = {"budget": budget, "active": active, "available": budget if active else 0,
                            "raw_deduction": 0, "applied_deduction": 0, "earned": budget if active else 0}
    # Severe findings receive cap budget first; input/report ordering cannot change attribution.
    order = {name: index for index, name in enumerate(DIMENSION_BUDGETS)}
    deductions = []
    for issue in sorted(issues.values(), key=lambda row: (order[row["dimension"]],
                        -SEVERITY_DEDUCTIONS[row["severity"]], row["fingerprint"], row["id"])):
        dim = dimensions[issue["dimension"]]
        raw = SEVERITY_DEDUCTIONS[issue["severity"]]
        applied = min(raw, dim["available"] - dim["applied_deduction"])
        dim["raw_deduction"] += raw
        dim["applied_deduction"] += applied
        dim["earned"] -= applied
        deductions.append({"issue_id": issue["id"], "dimension": issue["dimension"],
                           "severity": issue["severity"], "raw": raw, "applied": applied})
    total = sum(row["available"] for row in dimensions.values())
    for row in dimensions.values():
        row["normalized_weight"] = round(100 * row["available"] / total, 4) if total else 0
    observed = any(row["status"] in {"pass", "fail"} for row in results.values())
    value = round(100 * sum(row["earned"] for row in dimensions.values()) / total, 2) if total and observed else None
    provisional = any(row["status"] == "unverified" for row in results.values())
    grade = None
    if value is not None and not provisional:
        grade = "A" if value >= 90 else "B" if value >= 80 else "C" if value >= 70 else "D"
    return {"value": value, "grade": grade, "provisional": provisional,
            "scope": plan["scope"]["coverage"], "active_budget": total,
            "dimensions": dimensions, "deductions": deductions}
