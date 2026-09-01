import re
from collections import Counter


STOP = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for",
    "is", "are", "am", "i", "me", "my", "you", "your", "it", "this",
    "that", "with", "was", "were", "be", "do", "did", "what", "where",
    "when", "how", "why", "about", "tell", "remember"
}


HISTORICAL_TERMS = {
    "previous",
    "previously",
    "former",
    "before",
    "past",
    "earlier",
    "old",
    "used",
    "company",
    "companies",
    "employer",
    "employers",
}

def tokens(text):
    text = text.lower()

    # Normalize common spelling mistakes and semantic synonyms.
    replacements = {
        "cuurent": "current",
        "curent": "current",
        "comapny": "company",
        "comapnies": "companies",
        "emplyer": "employer",
        "employeer": "employer",
        "companies": "company",
        "employer": "company",
        "employers": "company",
    }

    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    return [
        x
        for x in re.findall(r"[a-zA-Z0-9']+", text)
        if x not in STOP
    ]


def is_historical_query(query):
    query_tokens = set(tokens(query))
    return bool(query_tokens & HISTORICAL_TERMS)


def score(query, memory):
    q = Counter(tokens(query))

    memory_text = (
        f"{memory['category']} "
        f"{memory['subject']} "
        f"{memory['predicate']} "
        f"{memory['value']}"
    )

    m = Counter(tokens(memory_text))

    overlap = sum(min(q[k], m[k]) for k in q)

    if not q:
        return 0.0

    confidence = float(memory["confidence"])

    return (
        (overlap / max(1, len(q))) * 0.75
        + confidence * 0.2
    )


def retrieve(db, query, limit=5):
    historical = is_historical_query(query)

    memories = db.active_memories()

    # Historical questions can use old/superseded memories.
    if historical:
        rows = db.conn.execute("""
            SELECT *
            FROM memories
            WHERE status='superseded'
            ORDER BY updated_at DESC
        """).fetchall()

        memories.extend(dict(row) for row in rows)

    ranked = sorted(
        ((score(query, memory), memory) for memory in memories),
        key=lambda x: x[0],
        reverse=True
    )

    selected = [
        memory
        for score_value, memory in ranked
        if score_value > 0
    ][:limit]

    db.mark_accessed([memory["id"] for memory in selected])

    return selected