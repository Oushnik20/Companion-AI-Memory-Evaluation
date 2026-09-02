import os
import re

from groq import Groq

from .persona import persona_prompt
from .prompts import RESPONSE_SYSTEM_TEMPLATE
from .memory import MemoryManager
from .retrieval import retrieve

def is_previous_employer_query(text):
    text = text.lower().strip()

    patterns = [
        r"\bprevious (?:company|companies|employer|employers)\b",
        r"\bformer (?:company|companies|employer|employers)\b",
        r"\bpast (?:company|companies|employer|employers)\b",
        r"\b(?:company|companies|employer|employers) i worked at before\b",
        r"\bwhere did i work before\b",
        r"\bwhat did i work at before\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)


def is_current_employer_query(text):
    text = text.lower().strip()

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
        r"\bcurrent (?:company|employer)\b",
        r"\bmy (?:current )?(?:company|employer)\b",
        r"\bwhere do i (?:currently )?work\b",
        r"\bwhere am i (?:currently )?working\b",
        r"\bwho do i work for\b",
        r"\bwhat company do i work (?:at|for)\b",
        r"\bwhat company\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)


def is_name_query(text):
    text = text.lower().strip()

    patterns = [
        r"\bmy name\b",
        r"\bwhat(?:'s| is) my name\b",
        r"\bdo you (?:know|remember) my name\b",
        r"\bcan you (?:tell me )?my name\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)


def is_location_query(text):
    text = text.lower().strip()

    patterns = [
        r"\bmy location\b",
        r"\bwhere do i live\b",
        r"\bwhere am i living\b",
        r"\bwhat city do i live in\b",
        r"\bdo you know where i live\b",
        r"\bwhat(?:'s| is) my location\b",
        r"\bwhich city do i live in\b",
    ]

    return any(re.search(pattern, text) for pattern in patterns)


def is_factual_memory_query(text):
    return (
        is_name_query(text)
        or is_location_query(text)
        or is_current_employer_query(text)
        or is_previous_employer_query(text)
    )


def direct_memory_answer(db, user_text):
    """
    Answer simple factual memory questions directly from SQLite.

    Returns:
        str | None
        None means the question should be handled by Groq.
    """

    # Name
    if is_name_query(user_text):
        memory = db.find_active_by_key("user", "name")

        if memory and float(memory["confidence"]) >= 0.75:
            db.mark_accessed([memory["id"]])
            return f"Your name is {memory['value']}."

        return None

    # Current location
    if is_location_query(user_text):
        memory = db.find_active_by_key("user", "current_location")

        if memory and float(memory["confidence"]) >= 0.75:
            db.mark_accessed([memory["id"]])
            return f"You live in {memory['value']}."

        return None

    # Current employer
    if is_current_employer_query(user_text):
        memory = db.find_active_by_key("user", "employer")

        if memory and float(memory["confidence"]) >= 0.75:
            db.mark_accessed([memory["id"]])
            return f"You currently work at {memory['value']}."

        return None

    # Previous employer(s)
    if is_previous_employer_query(user_text):
        memories = db.historical_employers()

        memories = [
            memory
            for memory in memories
            if float(memory["confidence"]) >= 0.75
        ]

        if not memories:
            return None

        db.mark_accessed([memory["id"] for memory in memories])

        values = []
        seen = set()

        for memory in memories:
            value = memory["value"].strip()

            if value.lower() not in seen:
                values.append(value)
                seen.add(value.lower())

        # Singular question
        singular = not re.search(
            r"\b(previous companies|previous employers|"
            r"former companies|former employers|"
            r"past companies|past employers|"
            r"what companies)\b",
            user_text.lower(),
        )

        if singular:
            return f"Your previous company was {values[0]}."

        if len(values) == 1:
            return f"Your previous employer was {values[0]}."

        formatted = "\n".join(f"- {value}" for value in values)

        return (
            "Your previous employers, according to the records I have, are:\n"
            f"{formatted}"
        )

    return None


class Companion:
    def __init__(self, db, model=None):
        self.db = db

        self.client = Groq(
            api_key=os.environ["GROQ_API_KEY"]
        )

        self.model = model or os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-20b",
        )

        self.memory = MemoryManager(
            db,
            self.client,
            model=self.model,
        )

        self.history = []

    def respond(self, user_text):
        self.db.decay_memories()

        # ---------------------------------------------------------
        # STEP 1: Memory-first routing
        # ---------------------------------------------------------
        #
        # For precise factual questions, check SQLite first.
        # If a high-confidence answer exists, return it directly.
        #
        # This avoids an unnecessary Groq call.
        # ---------------------------------------------------------

        if is_factual_memory_query(user_text):
            direct_answer = direct_memory_answer(
                self.db,
                user_text,
            )

            if direct_answer:
                self.history.append(
                    {
                        "user": user_text,
                        "assistant": direct_answer,
                    }
                )

                return direct_answer

        # ---------------------------------------------------------
        # STEP 2: Extract new memories
        # ---------------------------------------------------------
        #
        # Only do LLM-based memory extraction when the user message
        # can actually introduce/update information.
        #
        # A factual question itself normally does not add memory.
        # ---------------------------------------------------------

        if not is_factual_memory_query(user_text):
            self.memory.extract_and_store(user_text)

        # ---------------------------------------------------------
        # STEP 3: Retrieve relevant memories
        # ---------------------------------------------------------

        if is_previous_employer_query(user_text):
            memories = self.db.historical_employers()

        elif is_current_employer_query(user_text):
            current = self.db.find_active_by_key(
                "user",
                "employer",
            )
            memories = [dict(current)] if current else []

        else:
            memories = retrieve(
                self.db,
                user_text,
                limit=5,
            )

        # ---------------------------------------------------------
        # STEP 4: Groq response
        # ---------------------------------------------------------

        memory_text = "\n".join(
            (
                f"- {memory['category']}: "
                f"{memory['subject']}.{memory['predicate']} = "
                f"{memory['value']} "
                f"(confidence={memory['confidence']:.2f})"
            )
            for memory in memories
        )

        recent_conversation = "\n".join(
            f"User: {item['user']}\nMira: {item['assistant']}"
            for item in self.history[-8:]
        )

        system_prompt = (
            RESPONSE_SYSTEM_TEMPLATE
            .replace("{persona}", persona_prompt())
            .replace(
                "{conversation}",
                recent_conversation or "No recent conversation."
            )
            .replace(
                "{memories}",
                memory_text or "No relevant long-term memories."
            )
        )

        try:
            result = self.client.chat.completions.create(
                model=self.model,
                temperature=0.7,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_text,
                    },
                ],
            )
        except Exception as exc:
            if "tokens per day (tpd)" in str(exc).lower():
                return (
                    "I can't answer that right now. "
                    "My AI service quota is temporarily exhausted. "
                    "Please try again in a little while."
                )
            raise

        response = (
            result.choices[0].message.content or ""
        ).strip()

        self.history.append(
            {
                "user": user_text,
                "assistant": response,
            }
        )

        return response