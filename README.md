# Companion-AI Core Loop: Memory & Evaluation

A minimal CLI-based AI companion focused on **persistent memory, relevant retrieval, contradiction handling, and memory decay**.

The companion is powered by Groq and stores long-term memories in SQLite so that important facts can persist across conversations and sessions.

---

## Features

* CLI chat interface with a defined companion persona
* Persistent long-term memory using SQLite
* LLM-based memory extraction
* Confidence-based memory filtering
* Relevant memory retrieval instead of sending the entire database to the LLM
* Current vs. historical employer handling
* Memory updates and contradiction handling
* Memory confidence decay over time
* Recent conversation context
* Graceful handling of temporary Groq quota/rate-limit failures
* Optional evaluation harness with synthetic test cases

---

## Architecture

```text
User
 │
 ▼
CLI (app.py)
 │
 ▼
Companion.respond()
 │
 ├── Memory-first routing
 │      └── SQLite lookup for simple factual queries
 │
 ├── Memory extraction
 │      └── Groq LLM
 │
 ├── Memory storage
 │      └── SQLite
 │
 ├── Memory retrieval
 │      └── Relevant memories only
 │
 └── Response generation
        └── Groq LLM
```

### Main components

```text
app.py
  └── CLI entry point

companion/chat.py
  └── Main conversation loop
  └── Memory-first routing
  └── Context construction
  └── LLM response generation

companion/memory.py
  └── LLM-based memory extraction
  └── JSON parsing
  └── Confidence filtering

companion/retrieval.py
  └── Relevant memory retrieval

companion/persona.py
  └── Mira's stable persona and opinions

companion/prompts.py
  └── Memory extraction and response prompts

storage/database.py
  └── SQLite persistence
  └── Memory updates
  └── Contradiction handling
  └── Memory access tracking
  └── Memory decay

evaluation/
  ├── test_cases.json
  └── run_eval.py
```

---

## How Memory Works

The system separates **short-term conversation context** from **long-term memory**.

### 1. Memory extraction

When the user provides potentially useful information, the system asks the LLM to extract structured memories.

A memory contains:

```text
category
subject
predicate
value
confidence
source_text
```

For example:

```text
category: work
subject: user
predicate: employer
value: Microsoft
confidence: 0.92
```

Only memories above the configured confidence threshold are stored.

---

### 2. Persistent storage

Memories are stored in SQLite.

This means they survive after the CLI process exits and can be used in a later session.

The database is created automatically under:

```text
data/companion.db
```

---

### 3. Relevant retrieval

The system does not send the complete memory database to the LLM for every message.

Instead, it retrieves memories relevant to the current user message and limits the amount of memory placed into the response context.

This keeps the context focused and reduces unnecessary token usage.

---

### 4. Contradiction and updates

Mutable facts are updated when new information conflicts with an existing fact.

For example:

```text
User: I work at Google.
```

Later:

```text
User: I joined Microsoft.
```

The current employer is updated to Microsoft.

For employment history, the previous employer is preserved separately rather than being lost.

This allows the system to distinguish between:

```text
Current employer
Previous employer
```

---

### 5. Memory access and decay

Memories track when they were last accessed.

Old memories that are not accessed or refreshed gradually lose confidence.

Decay is bounded by a minimum confidence value so that memories do not disappear immediately simply because they are old.

When a memory is accessed again, its access timestamp is refreshed.

---

## Persona

The companion is named **Mira**.

Mira is designed to be:

* Warm and attentive
* Curious without being intrusive
* Lightly playful when appropriate
* Honest about uncertainty
* Calm under pressure

The persona is defined separately from the memory system so that memory behavior and conversational style remain independent.

---

## Running the Project

### Requirements

* Python 3.10+
* A Groq API key

### 1. Clone or extract the repository

```bash
git clone <your-repository-url>
cd companion-ai
```

Or simply open the extracted project directory.

### 2. Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-20b
```

Do not commit `.env` or expose the API key.

### 5. Run

```bash
python app.py
```

You should see:

```text
Mira is online. Type 'exit' to quit or 'memories' to inspect active memories.
```

Type:

```text
exit
```

to stop the application.

You can also type:

```text
memories
```

to inspect the currently stored active memories.

---

## Example

A typical interaction can look like:

```text
You: My name is Roya.
Mira: Nice to meet you, Roya.

You: I work at Microsoft.
Mira: Got it.

You: What is my name?
Mira: Your name is Roya.

You: What is my current company?
Mira: You currently work at Microsoft.
```

The important facts are stored in SQLite and remain available after restarting the application.

---

## Evaluation

An evaluation harness is included under:

```text
evaluation/
```

The test set contains synthetic scenarios covering:

* Long-range memory recall
* Employer contradiction
* Preference recall
* Current employer
* Previous employer
* Historical employer preservation
* Identity recall
* Location recall

Run it with:

```bash
python evaluation/run_eval.py
```

The evaluation is intentionally lightweight because the primary goal of the assignment is the **memory system itself**, rather than building a large evaluation framework.

---

## Design Decisions

### SQLite instead of an external vector database

SQLite was chosen because the assignment is a single-user, local prototype and does not require production-scale infrastructure.

It provides:

* Persistent storage
* Simple setup
* Easy inspection
* Deterministic updates
* No external database dependency

For this scope, a full vector database would add complexity without providing enough benefit.

### Structured memories instead of storing raw conversation

Long-term memory is represented as structured facts rather than simply saving the entire conversation.

This makes it possible to:

* Retrieve specific facts
* Update conflicting facts
* Track confidence
* Track access
* Apply decay

### Confidence filtering

The LLM can produce uncertain or irrelevant candidate memories.

The system therefore validates the extracted structure and ignores memories below the configured confidence threshold.

### Separate current and historical employment

Employment is a useful example of a mutable fact.

Instead of overwriting the old employer permanently, the system preserves historical employers so the companion can answer both:

```text
Where do I work now?
```

and:

```text
Where did I work before?
```

### Memory-first routing

Simple factual questions such as name, location, and employer can be answered directly from high-confidence stored memories.

This avoids unnecessary LLM calls and makes factual recall deterministic when the required memory already exists.

---

## What I Tried / Abandoned

### Direct LLM-only factual recall

An early approach relied on the LLM to answer factual memory questions every time.

This was less reliable because the model could fail to use the correct stored fact or require an unnecessary LLM call.

The current implementation checks high-confidence factual memories directly first.

### Sending all memories to the LLM

Another possible approach is to include the entire memory table in every prompt.

This was avoided because it increases context size and can introduce irrelevant information.

The current implementation retrieves only relevant memories.

### External vector database

A vector database was not used because the assignment does not require production-scale infrastructure and SQLite is sufficient for the scope of this prototype.

---

## Limitations

* The memory extractor depends on the LLM producing valid structured JSON.
* Retrieval is intentionally lightweight and is not a full semantic vector-search system.
* The system is designed as a local single-user prototype.
* Memory decay is heuristic rather than learned.
* The companion currently depends on Groq availability for extraction and general response generation.
* If the Groq quota is temporarily exhausted, existing high-confidence factual memories can still be answered through the memory-first path, while new LLM-based responses are temporarily unavailable.

---

## Out of Scope

The implementation intentionally does not include:

* UI polish
* Authentication
* Billing
* Multi-user support
* Voice
* Image/video features
* Production-scale infrastructure

These are outside the scope of the assignment.

---

## Project Structure

```text
companion-ai/
│
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
│
├── companion/
│   ├── __init__.py
│   ├── chat.py
│   ├── memory.py
│   ├── persona.py
│   ├── prompts.py
│   └── retrieval.py
│
├── storage/
│   ├── __init__.py
│   └── database.py
│
├── evaluation/
│   ├── __init__.py
│   ├── test_cases.json
│   └── run_eval.py
│
└── data/
    └── .gitkeep
```

---

## Summary

The project focuses on the core companion loop:

```text
Conversation
    ↓
Extract useful facts
    ↓
Persist structured memories
    ↓
Retrieve relevant memories
    ↓
Update / preserve contradictions
    ↓
Decay stale memories
    ↓
Generate a consistent response
```

The main design goal is to keep the implementation **small, inspectable, and focused on persistent memory behavior** rather than adding infrastructure outside the assignment scope.
