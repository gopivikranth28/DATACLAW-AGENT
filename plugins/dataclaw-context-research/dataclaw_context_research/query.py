"""Concept-driven query generation for open-world context research."""

from __future__ import annotations

import json
import re
from typing import Any

from dataclaw_data.registry import find_dataset
from dataclaw.providers.llm.provider import TextDeltaEvent
from dataclaw.schema import Message


STOP_WORDS = {
    "id", "ids", "key", "name", "date", "time", "type", "status", "value",
    "count", "number", "num", "total", "table", "data", "file", "csv",
    "train", "test", "sample", "submission", "predict", "predicting",
    "understand", "why", "after", "before", "from", "with", "using",
    "perform", "deep", "external", "research", "identify", "create",
    "dispatch", "parallel", "branches", "subagents", "compare", "against",
    "provided", "only", "baseline", "modeling", "candidates", "enrichment",
    "hypotheses", "experiment", "experiments", "all", "and", "the",
}

DOMAIN_HINTS = {
    "healthcare": {"patient", "diagnosis", "readmission", "hospital", "a1c", "glucose", "claim", "provider"},
    "finance": {"loan", "credit", "default", "balance", "transaction", "fraud", "claim", "premium", "risk", "payment"},
    "retail": {"product", "sales", "store", "customer", "sku", "order", "price", "quantity", "inventory"},
    "real estate": {"saleprice", "sale", "house", "home", "garage", "lot", "zoning", "basement", "bedroom", "bath", "property"},
    "saas": {"churn", "subscription", "mrr", "arr", "plan", "account", "tenant", "usage", "onboarding", "cancel", "paying"},
    "mobility": {"trip", "pickup", "dropoff", "fare", "driver", "vehicle", "route", "latitude", "longitude"},
    "survey": {"survey", "response", "rating", "score", "satisfaction", "nps", "question"},
    "climate": {"temperature", "rainfall", "emissions", "weather", "carbon", "station", "precipitation"},
    "education / learning analytics": {
        "student", "learner", "education", "educational", "school", "classroom",
        "course", "game", "gameplay", "assessment", "performance", "knowledge",
        "tutor", "learning", "event", "session", "level", "correct", "answer",
    },
}

OBJECTIVE_HINTS = {
    "prediction": {"target", "label", "outcome", "price", "default", "churn", "readmission", "fraud", "predict", "risk"},
    "forecasting": {"date", "time", "month", "week", "demand", "sales", "volume"},
    "segmentation": {"customer", "user", "account", "cluster", "segment"},
    "anomaly detection": {"fraud", "outlier", "alert", "incident", "failure"},
    "causal/diagnostic analysis": {"why", "driver", "drivers", "cause", "causes", "impact", "effect", "understand"},
    "sequence prediction": {"event", "events", "log", "logs", "session", "sequence", "sequential", "clickstream", "elapsed", "duration"},
}

DOMAIN_PROFILES = {
    "healthcare": {
        "research_terms": ["clinical risk modeling", "patient outcomes", "care pathway analytics"],
        "external_context": ["clinical guidelines", "public health statistics", "comorbidity indices"],
        "risks": ["data leakage", "coding bias", "health equity", "temporal validation"],
    },
    "finance": {
        "research_terms": ["credit risk modeling", "financial behavior analytics", "risk scoring"],
        "external_context": ["macroeconomic indicators", "credit bureau variables", "regulatory guidance"],
        "risks": ["fair lending bias", "reject inference", "time varying economic conditions"],
    },
    "retail": {
        "research_terms": ["consumer demand modeling", "customer analytics", "basket analysis"],
        "external_context": ["seasonality calendars", "promotion events", "regional economic signals"],
        "risks": ["promotion leakage", "stockout bias", "price endogeneity"],
    },
    "real estate": {
        "research_terms": ["residential property valuation", "hedonic pricing", "housing market appraisal"],
        "external_context": ["neighborhood amenities", "mortgage rates", "local housing market indices"],
        "risks": ["spatial autocorrelation", "market regime shift", "location leakage"],
    },
    "saas": {
        "research_terms": ["customer retention", "subscription churn", "product usage analytics"],
        "external_context": ["onboarding journey benchmarks", "pricing plan changes", "support interaction signals"],
        "risks": ["post-outcome leakage", "survivorship bias", "cohort drift"],
    },
    "mobility": {
        "research_terms": ["transport demand modeling", "urban mobility analytics", "spatiotemporal prediction"],
        "external_context": ["weather data", "public transit schedules", "traffic events"],
        "risks": ["geospatial leakage", "event confounding", "seasonality"],
    },
    "survey": {
        "research_terms": ["survey response analysis", "voice of customer analytics", "psychometric measurement"],
        "external_context": ["industry satisfaction benchmarks", "questionnaire design literature", "response bias studies"],
        "risks": ["nonresponse bias", "self selection bias", "measurement error"],
    },
    "climate": {
        "research_terms": ["climate risk modeling", "environmental time series", "remote sensing analytics"],
        "external_context": ["weather reanalysis", "satellite observations", "emissions inventories"],
        "risks": ["spatial leakage", "sensor drift", "trend nonstationarity"],
    },
    "education / learning analytics": {
        "research_terms": [
            "learning analytics",
            "educational data mining",
            "student performance prediction",
            "game based learning analytics",
            "intelligent tutoring systems",
        ],
        "external_context": [
            "knowledge tracing benchmarks",
            "curriculum metadata",
            "assessment item metadata",
            "learning science theory",
            "student engagement measures",
        ],
        "risks": [
            "student level leakage",
            "session temporal leakage",
            "assessment label leakage",
            "cold start learners",
            "classroom demographic bias",
        ],
    },
    "data analysis": {
        "research_terms": ["applied machine learning", "tabular data analysis", "predictive modeling"],
        "external_context": ["public benchmark datasets", "domain covariates", "official statistics"],
        "risks": ["data leakage", "sampling bias", "missing data mechanisms"],
    },
}

OBJECTIVE_PROFILES = {
    "prediction": {
        "research_terms": ["predictive modeling", "supervised learning", "risk prediction"],
        "methods": ["feature engineering", "model calibration", "cross validation", "benchmark models"],
        "evaluation": ["evaluation metrics", "validation protocol", "baseline comparison"],
    },
    "forecasting": {
        "research_terms": ["time series forecasting", "demand forecasting", "temporal modeling"],
        "methods": ["lag features", "rolling windows", "backtesting", "forecast reconciliation"],
        "evaluation": ["time split validation", "forecast accuracy metrics", "seasonality diagnostics"],
    },
    "segmentation": {
        "research_terms": ["customer segmentation", "behavioral clustering", "market segmentation"],
        "methods": ["clustering", "embedding features", "persona discovery"],
        "evaluation": ["cluster stability", "segment interpretability", "downstream lift"],
    },
    "anomaly detection": {
        "research_terms": ["anomaly detection", "outlier detection", "rare event detection"],
        "methods": ["unsupervised detection", "isolation forest", "threshold calibration"],
        "evaluation": ["precision recall", "alert fatigue", "false positive analysis"],
    },
    "causal/diagnostic analysis": {
        "research_terms": ["root cause analysis", "driver analysis", "causal inference"],
        "methods": ["confounder control", "sensitivity analysis", "counterfactual analysis"],
        "evaluation": ["effect size validation", "robustness checks", "triangulation"],
    },
    "analysis": {
        "research_terms": ["exploratory data analysis", "domain analysis", "evidence synthesis"],
        "methods": ["data profiling", "quality assessment", "hypothesis generation"],
        "evaluation": ["triangulation", "sensitivity checks", "source quality assessment"],
    },
    "sequence prediction": {
        "research_terms": ["sequential behavior modeling", "event log prediction", "clickstream modeling"],
        "methods": ["sequence features", "time since event features", "transformer sequence models", "hidden markov models"],
        "evaluation": ["grouped temporal validation", "next event prediction metrics", "student/session split validation"],
    },
}

TARGET_ALIASES = {
    "churn": ["customer attrition", "retention risk", "cancellation propensity", "subscription renewal"],
    "default": ["credit risk", "delinquency", "repayment failure", "loan performance"],
    "fraud": ["abuse detection", "suspicious activity", "financial crime", "transaction anomaly"],
    "readmission": ["hospital readmission", "care transition risk", "patient revisit", "post discharge outcome"],
    "saleprice": ["property value", "home appraisal", "residential valuation", "hedonic price"],
    "price": ["valuation", "price elasticity", "market value", "pricing model"],
    "score": ["rating outcome", "satisfaction score", "measurement scale", "survey score"],
    "sales": ["demand", "revenue", "purchase volume", "commercial performance"],
    "satisfaction": ["customer experience", "service quality", "voice of customer", "loyalty drivers"],
    "student performance": [
        "learning outcome prediction",
        "assessment performance",
        "knowledge mastery",
        "student success",
        "academic achievement",
    ],
}

PHRASE_TARGET_RULES = [
    (("stop paying", "cancel", "cancellation", "unsubscribe", "leave", "left", "attrit"), "churn"),
    (("poor satisfaction", "nps", "rating", "survey score"), "satisfaction"),
    (("sale price", "house price", "home price", "property value"), "saleprice"),
    (("late payment", "missed payment", "repayment", "delinquency"), "default"),
    (("student performance", "learning outcome", "assessment performance", "student success"), "student performance"),
]


def generate_queries(
    *,
    dataset_id: str = "",
    problem_statement: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    context = _collect_context(dataset_id=dataset_id, problem_statement=problem_statement)
    concepts = _extract_concepts(context)
    understanding = _understand_problem(
        context=context,
        concepts=concepts,
        problem_statement=problem_statement,
    )
    queries = _build_queries(understanding)

    deduped = []
    seen = set()
    for query in queries:
        query = _compact(query)
        normalized = " ".join(query.split()).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(query)
    return {
        "queries": deduped[: max(1, int(limit))],
        "inferred_domain": understanding["domain"],
        "inferred_objective": understanding["objective"],
        "concepts": concepts[:30],
        "problem_understanding": understanding,
        "generation_mode": "fallback",
    }


async def generate_queries_with_llm(
    *,
    llm: Any,
    dataset_id: str = "",
    problem_statement: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """Generate research queries with model understanding, falling back offline."""
    if llm is None or type(llm).__name__ == "MockLLM":
        return generate_queries(dataset_id=dataset_id, problem_statement=problem_statement, limit=limit)

    context = _collect_context(dataset_id=dataset_id, problem_statement=problem_statement)
    dataset_context = "\n".join(f"- {piece}" for piece in context[1:] if piece)
    system = """You generate high-quality external research queries for data science problems.
Return only valid JSON. Do not call tools.

Understand the actual real-world problem first. Ignore workflow instructions such as "perform deep research",
"dispatch subagents", "compare branches", or "before modeling". Do not merely reuse keywords.

Produce queries that would find existing research, benchmarks, datasets, methods, leakage risks,
domain constraints, and implementation references. Use conceptual synonyms and terms researchers would use,
even when they are absent from the user wording.

JSON schema:
{
  "problem_understanding": {
    "real_world_domain": string,
    "analytical_objective": string,
    "unit_of_analysis": string,
    "outcome_or_target": string,
    "data_modality": string,
    "source_context": string,
    "research_angles": string[],
    "external_enrichment_angles": string[],
    "validation_risks": string[]
  },
  "queries": string[]
}
"""
    user = f"""Problem statement:
{problem_statement or "(none provided)"}

Dataset/schema context:
{dataset_context or "(none provided)"}

Generate {max(1, int(limit))} source-diverse research queries. Prefer precise concepts over generic phrases like "applied machine learning" unless the problem is truly generic."""

    try:
        text_parts: list[str] = []
        async for event in llm.stream_turn([Message.user(user)], system=system, tools=[]):
            if isinstance(event, TextDeltaEvent):
                text_parts.append(event.text)
        payload = _parse_json_object("".join(text_parts))
        queries = [
            _compact(str(query))
            for query in payload.get("queries", [])
            if str(query).strip()
        ]
        if not queries:
            raise ValueError("LLM returned no queries")
        understanding = payload.get("problem_understanding", {})
        return {
            "queries": _dedupe(queries)[: max(1, int(limit))],
            "inferred_domain": understanding.get("real_world_domain", ""),
            "inferred_objective": understanding.get("analytical_objective", ""),
            "concepts": _extract_concepts([problem_statement, dataset_context])[:30],
            "problem_understanding": understanding,
            "generation_mode": "llm",
        }
    except Exception:
        fallback = generate_queries(dataset_id=dataset_id, problem_statement=problem_statement, limit=limit)
        fallback["generation_mode"] = "fallback_after_llm_error"
        return fallback


def _understand_problem(*, context: list[str], concepts: list[str], problem_statement: str) -> dict[str, Any]:
    text = " ".join(context).lower()
    phrase_target = _infer_target_from_phrases(text)
    target_terms = _target_terms(concepts, phrase_target)
    domain = _infer_domain(concepts, text)
    objective = _infer_objective(concepts, text)
    target = target_terms[0] if target_terms else phrase_target

    domain_profile = DOMAIN_PROFILES.get(domain, DOMAIN_PROFILES["data analysis"])
    objective_profile = OBJECTIVE_PROFILES.get(objective, OBJECTIVE_PROFILES["analysis"])
    target_aliases = TARGET_ALIASES.get(target, [])

    research_terms = _unique([
        *domain_profile["research_terms"],
        *objective_profile["research_terms"],
        *target_aliases,
    ])
    risk_terms = _unique([
        *domain_profile["risks"],
        *(_target_risks(target) if target else []),
        "missing data mechanisms",
        "data quality pitfalls",
    ])
    external_context = _unique(domain_profile["external_context"])
    methods = _unique(objective_profile["methods"])

    return {
        "domain": domain,
        "objective": objective,
        "target": target,
        "question": _research_question(problem_statement, domain, objective, target),
        "research_terms": research_terms[:8],
        "method_terms": methods[:6],
        "risk_terms": risk_terms[:6],
        "external_context_terms": external_context[:6],
        "salient_concepts": _salient_concepts(concepts, target=target, domain=domain)[:8],
        "source_angles": [
            "academic literature",
            "benchmark datasets",
            "maintained code repositories",
            "official/public data sources",
            "practitioner failure modes",
        ],
    }


def _build_queries(understanding: dict[str, Any]) -> list[str]:
    domain = str(understanding["domain"])
    objective = str(understanding["objective"])
    target = str(understanding.get("target") or "")
    research_terms = understanding["research_terms"]
    method_terms = understanding["method_terms"]
    risk_terms = understanding["risk_terms"]
    external_context = understanding["external_context_terms"]
    salient = understanding.get("salient_concepts", [])

    primary_research = _join_terms(research_terms[:3]) or domain
    secondary_research = _join_terms(research_terms[3:6]) or primary_research
    target_phrase = _join_terms([target, *TARGET_ALIASES.get(target, [])[:2]]) if target else primary_research
    methods = _join_terms(method_terms[:3])
    risks = _join_terms(risk_terms[:3])
    enrichments = _join_terms(external_context[:3])
    context_terms = _join_terms(salient[:4])

    queries = [
        f"{primary_research} {target_phrase} literature review benchmark dataset",
        f"{target_phrase} {context_terms} {methods} best practices",
        f"{primary_research} {context_terms} common pitfalls data leakage missing data",
        f"{secondary_research} evaluation metrics validation protocol baseline comparison",
        f"{domain} external data sources {enrichments} feature enrichment",
        f"{target_phrase} bias measurement error fairness robustness",
        f"{primary_research} github implementation reproducible examples",
        f"{domain} {target_phrase} official statistics public dataset covariates",
        f"{target_phrase} root cause drivers explanatory analysis",
        f"{primary_research} {risks} quality checks",
    ]
    return [q for q in queries if q.strip()]


def _collect_context(*, dataset_id: str, problem_statement: str) -> list[str]:
    pieces = [problem_statement] if problem_statement else []
    if dataset_id:
        dataset = find_dataset(dataset_id)
        pieces.extend([
            str(dataset.get("name", "")),
            str(dataset.get("description", "")),
            str(dataset.get("definition", "")),
        ])
        for table in dataset.get("tables") or []:
            pieces.append(str(table.get("name", "")))
            for column in table.get("column_details") or []:
                pieces.append(str(column.get("name", "")))
    return pieces


def _extract_concepts(parts: list[str]) -> list[str]:
    tokens: list[str] = []
    for part in parts:
        for raw in re.split(r"[^a-zA-Z0-9]+", _camel_to_words(part).lower()):
            if len(raw) < 3 or raw in STOP_WORDS:
                continue
            tokens.append(raw)
    ranked = sorted(set(tokens), key=lambda token: (-tokens.count(token), token))
    return ranked


def _infer_domain(concepts: list[str], text: str) -> str:
    if any(phrase in text for phrase in ("educational game", "student performance", "game play", "gameplay", "learning analytics")):
        return "education / learning analytics"
    if any(phrase in text for phrase in ("stop paying", "subscription", "onboarding", "cancel")):
        return "saas"
    if any(phrase in text for phrase in ("sale price", "house price", "home price", "property value")):
        return "real estate"
    return _infer_label(concepts, DOMAIN_HINTS) or "data analysis"


def _infer_objective(concepts: list[str], text: str) -> str:
    if any(word in text for word in ("why", "driver", "drivers", "cause", "causes", "understand", "explain")):
        return "causal/diagnostic analysis"
    if any(phrase in text for phrase in ("event logs", "game play event", "gameplay event", "clickstream", "sequential")):
        return "sequence prediction"
    if any(word in text for word in ("predict", "classify", "estimate", "score", "propensity", "risk")):
        return "prediction"
    if any(word in text for word in ("forecast", "future demand", "next month", "next week")):
        return "forecasting"
    return _infer_label(concepts, OBJECTIVE_HINTS) or "analysis"


def _infer_label(concepts: list[str], hints: dict[str, set[str]]) -> str:
    concept_set = set(concepts)
    best = ("", 0)
    for label, words in hints.items():
        score = len(concept_set & words)
        if score > best[1]:
            best = (label, score)
    return best[0]


def _infer_target_from_phrases(text: str) -> str:
    for phrases, target in PHRASE_TARGET_RULES:
        if any(phrase in text for phrase in phrases):
            return target
    return ""


def _target_terms(concepts: list[str], phrase_target: str = "") -> list[str]:
    priority = [
        c for c in concepts
        if c in {"target", "label", "outcome", "price", "churn", "default", "fraud", "score", "rating", "sales", "revenue", "saleprice", "satisfaction", "performance"}
    ]
    priority = ["student performance" if c == "performance" and "student" in concepts else c for c in priority]
    if phrase_target and phrase_target not in priority:
        priority.insert(0, phrase_target)
    return priority


def _target_risks(target: str) -> list[str]:
    if target == "churn":
        return ["post cancellation leakage", "cohort drift", "right censoring"]
    if target in {"price", "saleprice"}:
        return ["location leakage", "market shift", "appraisal bias"]
    if target == "default":
        return ["reject inference", "fair lending bias", "macroeconomic drift"]
    if target == "fraud":
        return ["label delay", "adversarial drift", "class imbalance"]
    if target == "satisfaction":
        return ["response bias", "measurement error", "self selection bias"]
    if target == "student performance":
        return ["student level leakage", "session temporal leakage", "assessment label leakage"]
    return []


def _salient_concepts(concepts: list[str], *, target: str, domain: str) -> list[str]:
    blocked = {target, *target.split(), *domain.replace("/", " ").split()}
    useful = []
    for concept in concepts:
        if concept in blocked or concept in STOP_WORDS:
            continue
        if concept in {"student", "educational", "education", "learning"}:
            continue
        useful.append(concept)
    return _unique(useful)


def _research_question(problem_statement: str, domain: str, objective: str, target: str) -> str:
    if problem_statement:
        return _compact(problem_statement)
    if target:
        return f"Find external context for {domain} {objective} around {target}."
    return f"Find external context for {domain} {objective}."


def _join_terms(terms: list[str]) -> str:
    return " ".join(term for term in terms if term)


def _unique(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = " ".join(str(value).split()).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(value))
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = " ".join(value.split()).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(stripped[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    return data


def _camel_to_words(value: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)


def _compact(value: str) -> str:
    return " ".join(value.split())[:180]
