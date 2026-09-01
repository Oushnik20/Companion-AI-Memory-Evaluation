import os
from dotenv import load_dotenv
from companion.chat import Companion
from storage.database import MemoryDB


def main():
    load_dotenv()

    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("Missing GROQ_API_KEY. Put it in .env")

    db = MemoryDB("data/companion.db")
    companion = Companion(db)

    print(
        "\nMira is online. "
        "Type 'exit' to quit or 'memories' to inspect active memories.\n"
    )

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user:
            continue

        if user.lower() in {"exit", "quit"}:
            print("Mira: Talk soon.")
            break

        if user.lower() == "memories":
            memories = db.active_memories()

            if not memories:
                print("No active memories.")
            else:
                for m in memories:
                    print(
                        f"- [{m['category']}] "
                        f"{m['subject']}.{m['predicate']} = "
                        f"{m['value']}"
                    )

            print()
            continue

        response = companion.respond(user)
        print(f"Mira: {response}\n")


if __name__ == "__main__":
    main()