import json
import os
import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from storage.database import MemoryDB
from companion.chat import Companion, direct_memory_answer


def contains_expected(text, expected):
    text = text.lower()
    return all(item.lower() in text for item in expected)


def run_case(companion, case):
    """
    Run one evaluation case using the real companion routing.

    The setup message is sent through the normal system because it may
    create memories. Subsequent turns also use the normal system.

    For simple factual questions, Companion uses the memory-first path
    and avoids Groq automatically.
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


def run_memory_only_case(db, case):
    """
    Test cases that should be answerable entirely from memory.

    This does not call Groq. It verifies that the memory-first layer
    can answer precise factual questions deterministically.
    """

    # Seed the memory directly so this test does not require Groq
    # for memory extraction.
    for memory in case["memories"]:
        db.add_memory(
            category=memory["category"],
            subject=memory["subject"],
            predicate=memory["predicate"],
            value=memory["value"],
            confidence=memory.get("confidence", 0.99),
            source_text=memory["source_text"],
        )

    answer = direct_memory_answer(
        db,
        case["question"],
    )

    if answer is None:
        return {
            "name": case["name"],
            "passed": False,
            "answer": "No deterministic memory answer available.",
            "groq_calls": 0,
        }

    passed = contains_expected(
        answer,
        case["expected"],
    )

    return {
        "name": case["name"],
        "passed": passed,
        "answer": answer,
        "groq_calls": 0,
    }


def run():
    load_dotenv()

    cases_path = Path("evaluation/test_cases.json")

    cases = json.loads(
        cases_path.read_text(encoding="utf-8")
    )

    # Separate deterministic memory tests from true LLM tests.
    memory_cases = [
        case
        for case in cases
        if case.get("type") == "memory_only"
    ]

    llm_cases = [
        case
        for case in cases
        if case.get("type") != "memory_only"
    ]

    results = []

    with tempfile.TemporaryDirectory() as td:
        db = MemoryDB(
            str(Path(td) / "eval.db")
        )

        # ---------------------------------------------------------
        # Phase 1: deterministic memory tests
        # ---------------------------------------------------------

        for case in memory_cases:
            results.append(
                run_memory_only_case(
                    db,
                    case,
                )
            )

        # ---------------------------------------------------------
        # Phase 2: genuine LLM evaluation
        # ---------------------------------------------------------

        companion = None

        if llm_cases:
            if not os.getenv("GROQ_API_KEY"):
                raise SystemExit(
                    "Missing GROQ_API_KEY"
                )

            companion = Companion(db)

            for case in llm_cases:
                results.append(
                    run_case(
                        companion,
                        case,
                    )
                )

        db.close()

    # -------------------------------------------------------------
    # Results
    # -------------------------------------------------------------

    passed = sum(
        result["passed"]
        for result in results
    )

    total = len(results)

    print()
    print("Evaluation Results")
    print("=" * 70)

    for result in results:
        status = "PASS" if result["passed"] else "FAIL"

        print(
            f"{status:4} | "
            f"{result['name']}"
        )

        print(
            f"      Answer: "
            f"{result['answer']}"
        )

        if "groq_calls" in result:
            print(
                f"      Groq calls: "
                f"{result['groq_calls']}"
            )

        print()

    score = (
        passed / total * 100
        if total
        else 0
    )

    print("=" * 70)
    print(
        f"Overall Score: "
        f"{passed}/{total} "
        f"({score:.1f}%)"
    )

    if passed == total:
        print(
            "Status: All evaluation cases passed."
        )
    else:
        print(
            "Status: Some evaluation cases failed."
        )

    print()


if __name__ == "__main__":
    run()