import json
from groq import Groq
from .prompts import MEMORY_EXTRACTION_PROMPT


class MemoryManager:
    def __init__(self, db, client, model):
        self.db = db
        self.client = client
        self.model = model

    def extract_and_store(self, user_text):
        """
        Extract durable user memories.

        Memory extraction is best-effort:
        if the LLM returns malformed output or the API fails,
        the conversation should continue normally.
        """
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

                events.append(
                    {
                        "id": memory_id,
                        "action": action,
                        "predicate": predicate,
                        "value": value,
                    }
                )

            return events

        except Exception as exc:
            # Memory is an enhancement, not a dependency of the chat loop.
            print(f"[memory extraction skipped: {exc}]")
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