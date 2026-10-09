"""파일 기반 글쓰기 실행을 시작·확인·완료한다. Python 표준 라이브러리만 사용한다.

python3 run_manager.py init --brief filled_brief.json
python3 run_manager.py status --run-dir runs/RUN_ID_HASH
python3 run_manager.py finalize --run-dir runs/RUN_ID_HASH --attempt 2
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from validate import compute_brief_hash, validate

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
REQUIRED = ("topic", "audience", "goal")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_seoul():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def init_run(brief_path):
    brief = read_json(brief_path)
    if not isinstance(brief, dict):
        raise ValueError("브리프는 JSON 객체여야 합니다")
    if any(not isinstance(brief.get(k), str) or not brief[k].strip() for k in REQUIRED):
        raise ValueError("브리프의 topic/audience/goal을 먼저 채워 주세요")
    materials = brief.get("verified_materials")
    if not isinstance(materials, list) or not materials or any(
        not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k].strip()
                                         for k in ("id", "kind", "source", "note"))
        for item in materials
    ):
        raise ValueError("verified_materials에 실제로 확인한 자료를 1개 이상 채워 주세요")
    local_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    run_id = brief.get("run_id") or f"{local_date}-tech-blog"
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{3,64}", run_id):
        raise ValueError("run_id는 영문·숫자·_·-로 된 3~64자여야 합니다")
    brief["run_id"] = run_id
    brief.pop("brief_hash", None)
    brief.pop("created_at", None)
    brief_hash = compute_brief_hash(brief)
    run_dir = RUNS / f"{run_id}_{brief_hash}"
    if run_dir.exists():
        raise FileExistsError(f"이미 있는 실행입니다: {run_dir}")
    brief["brief_hash"] = brief_hash
    brief["created_at"] = now_seoul()
    (run_dir / "attempts" / "01").mkdir(parents=True)
    write_json(run_dir / "01_input.json", brief)
    write_json(run_dir / "manifest.json", {
        "run_id": run_id, "brief_hash": brief_hash, "created_at": brief["created_at"],
        "status": "IN_PROGRESS", "final_attempt": None
    })
    (run_dir / "run_log.md").write_text(
        "# 실행 로그\n\n"
        f"- 실행 ID: `{run_id}`\n- 브리프 해시: `{brief_hash}`\n"
        "- 작성자: Claude Code 역할별 새 서브에이전트\n"
        "- 비평·평가 세션 식별자: 실행 후 기록\n\n"
        "| 시도 | 단계 | 입력 파일 | 출력 파일 | 에이전트/세션 | 결과·수정 이유 |\n"
        "|---:|---|---|---|---|---|\n"
        "| 1 | Gen | 01_input.json | attempts/01/02_output.json | 미작성 | 미작성 |\n"
        "| 1 | Critique | 01_input.json, attempts/01/02_output.json | attempts/01/03_critique.json | 미작성 | 미작성 |\n"
        "| 1 | Eval | 01_input.json, attempts/01/02_output.json, rubric.json | attempts/01/04_eval.json | 미작성 | 미작성 |\n"
        "| 1 | Validate | 위 파일들 | attempts/01/05_verdict.json | Python | 미작성 |\n"
        "| 2 | Refine | 1차 원고·비평·평가 | attempts/02/02_output.json, 02_changes.json | 미작성 | 미작성 |\n"
        "| 2 | Critique/Eval/Validate | 2차 원고·브리프·루브릭 | attempts/02/03~05 | 새 세션 | 미작성 |\n\n"
        "- 총 퇴고 횟수: 미작성\n- 루프 종료 지점과 이유: 미작성\n- 남은 문제: 미작성\n",
        encoding="utf-8"
    )
    return run_dir


def status(run_dir):
    brief = read_json(run_dir / "01_input.json")
    print(f"실행: {brief['run_id']} / {brief['brief_hash']}")
    for attempt_dir in sorted((run_dir / "attempts").glob("[0-9][0-9]")):
        names = ["02_output.json", "03_critique.json", "04_eval.json", "05_verdict.json"]
        found = [name for name in names if (attempt_dir / name).exists()]
        verdict_path = attempt_dir / "05_verdict.json"
        verdict = read_json(verdict_path).get("verdict") if verdict_path.exists() else "미판정"
        print(f"시도 {attempt_dir.name}: {', '.join(found) or '파일 없음'} / {verdict}")


def finalize(run_dir, attempt):
    if attempt not in (2, 3):
        raise ValueError("과제용 실행은 2차 초안이 필요하며, 퇴고는 최대 2회입니다")
    brief = read_json(run_dir / "01_input.json")
    attempt_dir = run_dir / "attempts" / f"{attempt:02}"
    draft = read_json(attempt_dir / "02_output.json")
    changes = read_json(attempt_dir / "02_changes.json")
    critique = read_json(attempt_dir / "03_critique.json")
    evaluation = read_json(attempt_dir / "04_eval.json")
    saved_verdict = read_json(attempt_dir / "05_verdict.json")
    rubric = read_json(ROOT / "rubric.json")
    if any(changes.get(key) != brief.get(key) for key in ("run_id", "brief_hash")) or changes.get("attempt") != attempt:
        raise ValueError("변경 기록의 실행 식별자 또는 시도 번호가 다릅니다")
    items = changes.get("changes")
    if not isinstance(items, list) or not items or any(
        not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip()
                                         for key in ("before", "after", "reason", "source_feedback"))
        for item in items
    ):
        raise ValueError("변경 기록에 이전·새 문장·이유·피드백 출처가 필요합니다")
    actual = validate(brief, draft, critique, evaluation, rubric, attempt)
    if actual != saved_verdict or actual["verdict"] != "PASS":
        raise ValueError("저장된 판정이 현재 파일과 다르거나 PASS가 아닙니다. 검증을 다시 실행하세요")
    (run_dir / "final.md").write_text(draft["content"].rstrip() + "\n", encoding="utf-8")
    manifest = read_json(run_dir / "manifest.json")
    manifest.update({"status": "READY_FOR_HUMAN_REVIEW", "final_attempt": attempt, "finalized_at": now_seoul()})
    write_json(run_dir / "manifest.json", manifest)
    return run_dir / "final.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p_init = commands.add_parser("init")
    p_init.add_argument("--brief", type=Path, required=True)
    p_status = commands.add_parser("status")
    p_status.add_argument("--run-dir", type=Path, required=True)
    p_final = commands.add_parser("finalize")
    p_final.add_argument("--run-dir", type=Path, required=True)
    p_final.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    if args.command == "init":
        print(init_run(args.brief))
    elif args.command == "status":
        status(args.run_dir)
    else:
        print(finalize(args.run_dir, args.attempt))


if __name__ == "__main__":
    main()
