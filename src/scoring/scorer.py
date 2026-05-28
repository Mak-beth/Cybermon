from src.scoring.rules import get_likelihood, get_impact


def calculate_likelihood(violation: dict) -> int:
    return get_likelihood(violation)


def calculate_impact(violation: dict) -> int:
    return get_impact(violation)


def calculate_score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def assign_severity(score: int, config: dict) -> str:
    tiers = config["scoring"]["severity_tiers"]
    for tier_name, bounds in tiers.items():
        if bounds["min"] <= score <= bounds["max"]:
            return tier_name.capitalize()
    return "Critical"


def score_violation(violation: dict, config: dict) -> dict:
    likelihood = calculate_likelihood(violation)
    impact = calculate_impact(violation)
    risk_score = calculate_score(likelihood, impact)
    severity = assign_severity(risk_score, config)
    return {
        **violation,
        "likelihood": likelihood,
        "impact": impact,
        "risk_score": risk_score,
        "severity": severity,
    }


def score_all_violations(violations: list[dict], config: dict) -> list[dict]:
    return [score_violation(v, config) for v in violations]
