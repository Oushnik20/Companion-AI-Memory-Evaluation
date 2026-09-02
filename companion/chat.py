import os
import re

from groq import Groq

from .persona import persona_prompt
from .prompts import RESPONSE_SYSTEM_TEMPLATE
from .memory import MemoryManager
from .retrieval import retrieve


DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

def is_previous_employer_query(text):
    text = text.lower()

    patterns = [
        r"\bprevious company\b",
        r"\bprevious companies\b",
        r"\bformer company\b",
        r"\bformer companies\b",
        r"\bprevious employer\b",
        r"\bprevious employers\b",
        r"\bformer employer\b",
        r"\bformer employers\b",
        r"\bpast employers\b",
        r"\bpast companies\b",
        r"\bcompanies i worked at before\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)

def is_current_employer_query(text):
    text = text.lower()

    # Normalize a few common spelling mistakes.
    typo_map = {
        "cuurent": "current",
        "curent": "current",
        "comapny": "company",
        "emplyer": "employer",
        "employeer": "employer",
    }

    for wrong, correct in typo_map.items():
        text = text.replace(wrong, correct)

    patterns = [
        r"\bcurrent company\b",
        r"\bcurrent employer\b",
        r"\bwhere do i work\b",
        r"\bwhere am i working\b",
        r"\bcompany do i work\b",
        r"\bcompany i work\b",
        r"\bwho do i work for\b",
        r"\bwhere do i currently work\b",
        r"\bwhat company\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)

class Companion:

    def __init__(self, db, model=DEFAULT_MODEL):
        self.db = db
        self.client = Groq(api_key=os.environ["GROQ_API_KEY"])
        self.model = model
        self.memory = MemoryManager(db, self.client, model)

    def respond(self, user_text):

        self.db.decay_memories()
        # Save the user message first.
        self.db.add_conversation("user", user_text)

        # Extract durable facts from the current message.
        self.memory.extract_and_store(user_text)

        if is_previous_employer_query(user_text):
            memories = self.db.historical_employers()
            memories = list(reversed(memories))
        elif is_current_employer_query(user_text):
            current = self.db.find_active_by_key("user", "employer")
            memories = [dict(current)] if current else []
        else:
            memories = retrieve(self.db, user_text, limit=5)

        memory_text = "\n".join(
            f"- {m['category']}: "
            f"{m['subject']} "
            f"{m['predicate']} = "
            f"{m['value']}"
            for m in memories
        ) or "- No relevant stored memories."

        # Include a small recent conversational window.
        recent_messages = self.db.recent_conversations(limit=8)

        conversation_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in recent_messages
        ) or "- No recent conversation."

        system = RESPONSE_SYSTEM_TEMPLATE.format(
            persona=persona_prompt(),
            memories=memory_text,
            conversation=conversation_text,
        )

        result = self.client.chat.completions.create(
            model=self.model,
            temperature=0.55,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
        )

        answer = result.choices[0].message.content.strip()

        self.db.add_conversation("assistant", answer)

        return answer