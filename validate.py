"""P3 기계 검증 + P5 점수 하한. Python 표준 라이브러리만 사용한다.

사용법:
python3 validate.py --brief runs/ID/01_input.json \
  --draft runs/ID/attempts/01/02_output.json \
  --critique runs/ID/attempts/01/03_critique.json \
  --evaluation runs/ID/attempts/01/04_eval.json \
  --attempt 1 --out runs/ID/attempts/01/05_verdict.json
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

AXES = ("structure", "evidence", "sentence", "uniqueness")


def nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def compute_brief_hash(brief):
    canonical_data = {k: v for k, v in brief.items() if k not in ("brief_hash", "created_at")}
    canonical = json.dumps(canonical_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def validate(brief, draft, critique, evaluation, rubric, expected_attempt):
    errors = []
    if not isinstance(brief, dict):
        brief = {}
        errors.append("brief: JSON 객체가 필요합니다")
    if not isinstance(draft, dict):
        draft = {}
        errors.append("draft: JSON 객체가 필요합니다")
    if not isinstance(evaluation, dict):
        evaluation = {}
        errors.append("evaluation: JSON 객체가 필요합니다")
    if not isinstance(critique, dict):
        critique = {}
        errors.append("critique: JSON 객체가 필요합니다")

    for key in ("run_id", "topic", "audience", "goal"):
        if not nonempty_string(brief.get(key)):
            errors.append(f"brief.{key}: 비어 있거나 문자열이 아닙니다")
    brief_hash = brief.get("brief_hash")
    if not isinstance(brief_hash, str) or not re.fullmatch(r"[a-f0-9]{12}", brief_hash):
        errors.append("brief.brief_hash: 12자리 16진수 식별자가 필요합니다")
    elif brief_hash != compute_brief_hash(brief):
        errors.append("brief.brief_hash: 브리프 내용이 실행 시작 후 변경됐습니다")
    for name, data in (("draft", draft), ("critique", critique), ("evaluation", evaluation)):
        if data.get("run_id") != brief.get("run_id"):
            errors.append(f"{name}.run_id: 브리프와 다릅니다")
        if data.get("brief_hash") != brief_hash:
            errors.append(f"{name}.brief_hash: 브리프와 다릅니다")
        if type(data.get("attempt")) is not int or data["attempt"] != expected_attempt:
            errors.append(f"{name}.attempt: 요청한 시도 번호 {expected_attempt}와 다릅니다")

    content = draft.get("content")
    if not nonempty_string(content):
        errors.append("draft.content: 제목과 본문이 필요합니다")
        content = ""

    weaknesses = critique.get("weaknesses")
    if not isinstance(weaknesses, list) or len(weaknesses) != 3:
        errors.append("critique.weaknesses: 약점 정확히 3개가 필요합니다")
    else:
        for index, item in enumerate(weaknesses):
            if not isinstance(item, dict) or any(
                not nonempty_string(item.get(key))
                for key in ("location", "problem", "revision_instruction")
            ):
                errors.append(f"critique.weaknesses[{index}]: 위치/문제/수정 지시가 필요합니다")

    bounds = brief.get("target_chars")
    if not isinstance(bounds, dict):
        bounds = {}
    lower, upper = bounds.get("min"), bounds.get("max")
    if type(lower) is not int or type(upper) is not int or not 0 < lower <= upper:
        errors.append("brief.target_chars: 양의 정수 min/max가 필요합니다")
    elif not lower <= len(content) <= upper:
        errors.append(f"length: 원고 {len(content)}자, 허용 범위 {lower}~{upper}자")

    materials = brief.get("verified_materials")
    if not isinstance(materials, list) or not materials:
        errors.append("brief.verified_materials: 확인 자료가 1개 이상 필요합니다")
    else:
        for index, item in enumerate(materials):
            if not isinstance(item, dict) or any(
                not nonempty_string(item.get(key)) for key in ("id", "kind", "source", "note")
            ):
                errors.append(f"brief.verified_materials[{index}]: id/kind/source/note가 필요합니다")

    constraints = brief.get("constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
        errors.append("brief.constraints: JSON 객체여야 합니다")
    banned_terms = constraints.get("banned_terms", [])
    if not isinstance(banned_terms, list) or any(not nonempty_string(x) for x in banned_terms):
        errors.append("brief.constraints.banned_terms: 문자열 목록이어야 합니다")
    else:
        for term in banned_terms:
            if term in content:
                errors.append(f"banned_term: '{term}'이 원고에 있습니다")

    axes = rubric.get("axes", {})
    weights = [axes.get(axis, {}).get("weight") for axis in AXES]
    if any(type(w) not in (int, float) or w < 0 for w in weights) or abs(sum(weights) - 1.0) > 1e-9:
        errors.append("rubric: 네 축의 가중치 합이 1.00이어야 합니다")

    scores = evaluation.get("scores")
    reasons = evaluation.get("reasons")
    if not isinstance(scores, dict):
        scores = {}
    if not isinstance(reasons, dict):
        reasons = {}
    for axis in AXES:
        score = scores.get(axis)
        if type(score) is not int or not 1 <= score <= 5:
            errors.append(f"scores.{axis}: 1~5 정수가 필요합니다")
        if not nonempty_string(reasons.get(axis)):
            errors.append(f"reasons.{axis}: 원고 위치를 포함한 근거가 필요합니다")
    total = sum(scores[axis] for axis in AXES) if all(type(scores.get(a)) is int and 1 <= scores[a] <= 5 for a in AXES) else None
    threshold = rubric.get("pass", {})
    if total is not None:
        if total < threshold["minimum_total_20"]:
            errors.append(f"quality: 총점 {total}/20, 요구 {threshold['minimum_total_20']}/20")
        for axis in AXES:
            if scores[axis] < threshold["minimum_each"]:
                errors.append(f"quality: {axis} {scores[axis]}점, 요구 {threshold['minimum_each']}점")

    if evaluation.get("topic_match") is not True:
        errors.append("topic_match: 원고가 브리프의 주제와 일치하지 않습니다")
    integrity = evaluation.get("factual_integrity")
    if not isinstance(integrity, dict) or type(integrity.get("pass")) is not bool or not isinstance(integrity.get("issues"), list):
        errors.append("factual_integrity: pass 불리언과 issues 목록이 필요합니다")
    elif integrity["pass"] is not True or integrity["issues"]:
        errors.append("factual_integrity: 근거 없는 기술 주장 또는 사실 확인 문제가 있습니다")
    code = evaluation.get("code_claims")
    if not isinstance(code, dict) or type(code.get("present")) is not bool or type(code.get("verified")) is not bool:
        errors.append("code_claims: present/verified 불리언이 필요합니다")
    elif code["present"] and (not code["verified"] or not nonempty_string(code.get("evidence"))):
        errors.append("code_claims: 코드 동작 주장에 실행 기록 등 확인 자료가 없습니다")

    return {
        "run_id": brief.get("run_id"),
        "brief_hash": brief_hash,
        "attempt": expected_attempt,
        "verdict": "PASS" if not errors else "REJECT",
        "draft_chars": len(content),
        "scores": scores,
        "total_20": total,
        "errors": errors,
        "note": "형식·길이·점수·평가자의 사실성 판정만 확인함. 출처의 실제 진위는 사람이 확인해야 함."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--draft", required=True, type=Path)
    parser.add_argument("--critique", required=True, type=Path)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    brief = json.loads(args.brief.read_text(encoding="utf-8"))
    draft = json.loads(args.draft.read_text(encoding="utf-8"))
    critique = json.loads(args.critique.read_text(encoding="utf-8"))
    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
    rubric = json.loads((root / "rubric.json").read_text(encoding="utf-8"))
    verdict = validate(brief, draft, critique, evaluation, rubric, args.attempt)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{verdict['verdict']} | {verdict['total_20']}/20 | {len(verdict['errors'])} errors | {args.out}")


if __name__ == "__main__":
    main()
