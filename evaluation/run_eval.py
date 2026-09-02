import json
import os
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# from pathlib import Path

from dotenv import load_dotenv

from storage.database import MemoryDB
from companion.chat import Companion


def contains_expected(text, expected):
    text = text.lower()
    return all(item.lower() in text for item in expected)


def run_case(companion, case):
    """
    Run one evaluation case and return the final answer and pass/fail result.
    """
    companion.respond(case["setup"])

    answer = ""
    for turn in case["turns"]:
        answer = companion.respond(turn)

    passed = contains_expected(answer, case["expected"])

    return {
        "name": case["name"],
        "passed": passed,
        "answer": answer,
    }


def run():
    load_dotenv()

    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("Missing GROQ_API_KEY")

    cases = json.loads(
        Path("evaluation/test_cases.json").read_text(encoding="utf-8")
    )

    results = []

    with tempfile.TemporaryDirectory() as td:
        db = MemoryDB(str(Path(td) / "eval.db"))
        companion = Companion(db)

        try:
            for case in cases[:4]:
                results.append(run_case(companion, case))
        finally:
            db.close()

    passed = sum(result["passed"] for result in results)
    total = len(results)

    print("\nEvaluation Results")
    print("=" * 70)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"

        print(f"{status:4} | {result['name']}")
        print(f"      Answer: {result['answer']}")
        print()

    score = (passed / total * 100) if total else 0

    print("=" * 70)
    print(f"Overall Score: {passed}/{total} ({score:.1f}%)")

    if passed == total:
        print("Status: All evaluation cases passed.")
    else:
        print("Status: Some evaluation cases failed.")

    print()


if __name__ == "__main__":
    run()