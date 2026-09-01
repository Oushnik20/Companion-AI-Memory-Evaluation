# Companion-AI: Memory & Personality Consistency

A small command-line AI companion prototype focused on the core problem in the assessment:
persistent memory, relevant retrieval, contradiction handling, and stable personality.

## Architecture

```text
User message
    |
    +--> Memory extraction (Groq)
    |       |
    |       +--> normalized fact
    |              |
    |              v
    |         SQLite memory store
    |              |
    |              +--> same key -> refresh
    |              +--> changed value -> supersede old memory
    |
    +--> relevance retrieval
    |       |
    |       v
    |   active memories only
    |
    v
Stable persona + retrieved memories + current message
    |
    v
Groq response
```

### Why SQLite?

The assignment requires memory to survive process restarts. SQLite provides durable local storage
without introducing infrastructure or a server dependency.

### Why structured memories?

A companion needs to answer questions such as "What do I do for work?" reliably. Each memory has
a category, subject, predicate, value, confidence, status, timestamps, and optional superseded link.
This makes updates deterministic and inspectable.

### Retrieval

The prototype uses lightweight lexical relevance scoring over active structured memories. It does
not dump the entire memory store into every prompt. This is intentionally simple and dependency-light.
The retrieval interface is isolated in `companion/retrieval.py`, so an embedding index can be added
without changing the memory or chat layers.

### Contradiction handling

Facts use a `(subject, predicate)` key. If a new high-confidence fact arrives for an existing key,
the previous fact is marked `superseded` and the new fact becomes `active`. Thus contradictory facts
are not blindly accumulated.

Example:

- `occupation = backend engineer` -> active
- `occupation = product role candidate` -> previous fact superseded, new fact active

### Personality consistency

The persona is defined separately in `companion/persona.py`. User memories cannot rewrite the
persona. The response prompt explicitly distinguishes stable persona instructions from user facts.

## Setup

Python 3.10+ recommended.

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```env
GROQ_API_KEY=your_key
GROQ_MODEL=openai/gpt-oss-20b
```

Never commit `.env`.

## Run

```bash
python app.py
```

Useful commands inside the chat:

```text
memories
exit
```

The database is created at `data/companion.db` and survives process restarts.

## Evaluation

Run:

```bash
python evaluation/run_eval.py
```

The included tests exercise long-range recall, contradiction handling, and preference recall.
The evaluator is deliberately lightweight: it checks whether the final answer contains the expected
facts. It is not a substitute for human judgment or an LLM-as-judge.

## What was tried / deliberately kept out

### No UI
The assessment explicitly allows a terminal loop and says UI polish is out of scope.

### No full conversation replay
Conversation history alone is not treated as memory. Durable facts are stored separately.

### No vector database
For this small prototype, a full vector database adds operational complexity. Retrieval is isolated
behind a small interface so semantic embeddings can be added later.

## Known limitations

1. Memory extraction depends on the LLM producing valid JSON.
2. The current contradiction key is subject + predicate; complex multi-valued facts may need richer
   entity resolution.
3. Retrieval is lexical rather than embedding-based, so paraphrases can be missed.
4. The evaluator is intentionally small and should be expanded to 50+ turns and include persona-drift
   judging for a stronger submission.
5. There is no multi-user authentication, UI, voice, or production infrastructure by design.

## Demo script

For a walkthrough, demonstrate:

1. Tell Mira a durable fact.
2. Exit the process.
3. Restart it and ask about the fact.
4. State a newer contradictory fact.
5. Ask the original question again and show that the newer fact wins.
6. Use `memories` to show active memory state.
7. Run the evaluation harness.

## Assessment mapping

- Persistence: SQLite database
- Memory extraction: `companion/memory.py`
- Relevant retrieval: `companion/retrieval.py`
- Update/decay: active/superseded memory states
- Character consistency: `companion/persona.py`
- Evaluation: `evaluation/`
