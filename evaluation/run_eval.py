import json
import os
import re
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from storage.database import MemoryDB
from companion.chat import Companion

def contains_expected(text, expected):
    text = text.lower()
    return all(x.lower() in text for x in expected)

def run():
    load_dotenv()
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("Missing GROQ_API_KEY")

    cases = json.loads(Path("evaluation/test_cases.json").read_text())
    results = []

    with tempfile.TemporaryDirectory() as td:
        db = MemoryDB(str(Path(td) / "eval.db"))
        companion = Companion(db)

        for case in cases:
            companion.respond(case["setup"])
            answer = ""
            for turn in case["turns"]:
                answer = companion.respond(turn)

            passed = contains_expected(answer, case["expected"])
            results.append((case["name"], passed, answer))

    passed = sum(x[1] for x in results)
    total = len(results)

    print("\nEvaluation Results")
    print("=" * 60)
    for name, ok, answer in results:
        print(f"{'PASS' if ok else 'FAIL':4} | {name}")
        print(f"      {answer}\n")
    print(f"Score: {passed}/{total} ({passed/total*100:.1f}%)")

if __name__ == "__main__":
    run()
