import json
import re
import time
from groq import Groq
from .prompts import MEMORY_EXTRACTION_PROMPT


class MemoryManager:
    def __init__(self, db, client, model):
        self.db = db
        self.client = client
        self.model = model

    def extract_and_store(self, user_text):
        max_retries = 3

        for attempt in range(max_retries):
            try:
                result = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0,
                    messages=[
                        {
                            "role": "system",
                            "content": MEMORY_EXTRACTION_PROMPT,
                        },
                        {
                            "role": "user",
                            "content": user_text,
                        },
                    ],
                )

                raw = (result.choices[0].message.content or "").strip()

                if not raw:
                    return []

                data = self._parse_json(raw)

                if not isinstance(data, dict):
                    return []

                memories = data.get("memories", [])

                if not isinstance(memories, list):
                    return []

                events = []

                for item in memories:
                    if not isinstance(item, dict):
                        continue

                    required = {
                        "category",
                        "subject",
                        "predicate",
                        "value",
                        "confidence",
                    }

                    if not required.issubset(item):
                        continue

                    try:
                        confidence = float(item["confidence"])
                    except (TypeError, ValueError):
                        continue

                    confidence = max(0.0, min(1.0, confidence))

                    if confidence < 0.55:
                        continue

                    category = str(item["category"]).strip()
                    subject = str(item["subject"]).strip()
                    predicate = str(item["predicate"]).strip()
                    value = str(item["value"]).strip()

                    if not category or not subject or not predicate or not value:
                        continue

                    memory_id, action = self.db.add_memory(
                        category=category,
                        subject=subject,
                        predicate=predicate,
                        value=value,
                        confidence=confidence,
                        source_text=user_text,
                    )

                    events.append({
                        "id": memory_id,
                        "action": action,
                        "predicate": predicate,
                        "value": value,
                    })

                return events

            except Exception as exc:
                error_text = str(exc).lower()

                is_tpd_limit = "tokens per day (tpd)" in error_text

                if is_tpd_limit:
                    fallback_events = self._fallback_extract(user_text)

                    if fallback_events:
                        print("[Groq quota exhausted; deterministic memory fallback used.]")

                    return fallback_events

                if "429" in error_text or "rate_limit" in error_text:
                    if attempt < max_retries - 1:
                        wait_seconds = 3 * (attempt + 1)
                        print(
                            f"[Groq rate limit; retrying in "
                            f"{wait_seconds}s...]"
                        )
                        time.sleep(wait_seconds)
                        continue

                print(f"[memory extraction skipped: {exc}]")
                return []

        return []

    def _fallback_extract(self, user_text):
            """
            Extract a small set of unambiguous personal facts without
            requiring the LLM.

            This is intentionally conservative. Complex statements still
            go through the LLM extractor.
            """

            text = user_text.strip()

            patterns = [
                (
                    r"^(?:my name is|i am|i'm)\s+([A-Za-z][A-Za-z .'-]{1,60})$",
                    "user",
                    "name",
                ),
                (
                    r"^(?:i work at|i am working at|i'm working at|i am now working at|i'm now working at|i now work at)\s+(.+?)$",
                    "work",
                    "employer",
                ),
                (
                    r"^(?:i live in|i    am living in|i'm living in)\s+(.+?)$",
                    "user",
                    "current_location",
                ),
            ]

            for pattern, category, predicate in patterns:
                match = re.match(pattern, text, re.IGNORECASE)

                if not match:
                    continue

                value = match.group(1).strip(" .,!?:;")

                if not value:
                    return []

                memory_id, action = self.db.add_memory(
                    category=category,
                    subject="user",
                    predicate=predicate,
                    value=value,
                    confidence=0.98,
                    source_text=user_text,
                )

                return [
                    {
                        "id": memory_id,
                        "action": action,
                        "predicate": predicate,
                        "value": value,
                    }
                ]

            return []

    @staticmethod
    def _parse_json(raw):
        """
        Parse JSON even when the model wraps it in markdown
        or adds a small amount of surrounding text.
        """

        # First attempt: exact JSON.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Remove markdown code fences.
        cleaned = (
            raw.replace("```json", "")
            .replace("```JSON", "")
            .replace("```", "")
            .strip()
        )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Last attempt: extract the outermost JSON object.
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end > start:
            candidate = cleaned[start : end + 1]

            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        raise ValueError("LLM returned invalid JSON")