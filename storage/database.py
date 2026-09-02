import sqlite3
from datetime import datetime, timezone
from pathlib import Path

def now():
    return datetime.now(timezone.utc).isoformat()

class MemoryDB:
    def __init__(self, path="data/companion.db"):
        self.path = Path(path)

        # Create data directory automatically
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            subject TEXT NOT NULL,
            predicate TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.8,
            status TEXT NOT NULL DEFAULT 'active',
            supersedes_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT,
            last_decayed_at TEXT,
            source_text TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_memory_status ON memories(status);
        CREATE INDEX IF NOT EXISTS idx_memory_key
            ON memories(subject, predicate, status);

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
        self.conn.commit()

        # Normalize legacy AWS memory.
        self.conn.execute("""
            UPDATE memories
            SET category='technology',
                predicate='platform'
            WHERE category='preference'
              AND LOWER(value)='aws'
        """)

        # Normalize legacy company memories.
        self.conn.execute("""
            UPDATE memories
            SET category='work',
                predicate='employer'
            WHERE category='technology'
              AND LOWER(value) IN ('paytm', 'zoom')
        """)

        self.conn.commit()

    def add_conversation(self, role, content):
        self.conn.execute(
            "INSERT INTO conversations(role, content, created_at) VALUES(?,?,?)",
            (role, content, now())
        )
        self.conn.commit()

    def recent_conversations(self, limit=8):
        rows = self.conn.execute("""
            SELECT role, content, created_at
            FROM conversations
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return list(reversed(rows))

    def find_active_by_key(self, subject, predicate):
        return self.conn.execute("""
            SELECT * FROM memories
            WHERE subject=? AND predicate=? AND status='active'
            ORDER BY updated_at DESC LIMIT 1
        """, (subject, predicate)).fetchone()

    def add_memory(self, category, subject, predicate, value, confidence, source_text):
        # Historical employers are append-only.
        # A new previous employer must never replace an older one.
        if predicate == "previous_employer":
            existing = self.conn.execute("""
                SELECT *
                FROM memories
                WHERE subject=?
                AND predicate='previous_employer'
                AND LOWER(value)=LOWER(?)
                AND status='active'
                LIMIT 1
            """, (subject, value)).fetchone()

            if existing:
                self.conn.execute("""
                    UPDATE memories
                    SET confidence=?,
                        updated_at=?,
                        source_text=?
                    WHERE id=?
                """, (
                    max(existing["confidence"], confidence),
                    now(),
                    source_text,
                    existing["id"],
                ))
                self.conn.commit()

                return existing["id"], "refreshed"

            self.conn.execute("""
                INSERT INTO memories(
                    category,
                    subject,
                    predicate,
                    value,
                    confidence,
                    status,
                    created_at,
                    updated_at,
                    source_text
                )
                VALUES(?,?,?,?,?,'active',?,?,?)
            """, (
                category,
                subject,
                predicate,
                value,
                confidence,
                now(),
                now(),
                source_text,
            ))
            self.conn.commit()

            return self.conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0], "created"

        # Normal memories represent one current value
        # for each subject/predicate pair.
        existing = self.find_active_by_key(subject, predicate)

        if existing:
            # Same fact -> refresh confidence/source instead of creating duplicate.
            if existing["value"].strip().lower() == value.strip().lower():
                self.conn.execute("""
                    UPDATE memories
                    SET confidence=?,
                        updated_at=?,
                        source_text=?
                    WHERE id=?
                """, (
                    max(existing["confidence"], confidence),
                    now(),
                    source_text,
                    existing["id"],
                ))
                self.conn.commit()

                return existing["id"], "refreshed"

            # Employer changed:
            # preserve the old current employer as a historical employer.
            if predicate == "employer":
                self.conn.execute("""
                    UPDATE memories
                    SET predicate='previous_employer',
                        status='active',
                        supersedes_id=NULL,
                        updated_at=?
                    WHERE id=?
                """, (
                    now(),
                    existing["id"],
                ))
            else:
                # For other mutable memories, supersede the old value.
                self.conn.execute("""
                    UPDATE memories
                    SET status='superseded',
                        updated_at=?
                    WHERE id=?
                """, (
                    now(),
                    existing["id"],
                ))

            # Insert the new current value.
            self.conn.execute("""
                INSERT INTO memories(
                    category,
                    subject,
                    predicate,
                    value,
                    confidence,
                    status,
                    supersedes_id,
                    created_at,
                    updated_at,
                    source_text
                )
                VALUES(?,?,?,?,?,'active',?,?,?,?)
            """, (
                category,
                subject,
                predicate,
                value,
                confidence,
                existing["id"],
                now(),
                now(),
                source_text,
            ))
            self.conn.commit()

            return self.conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0], "superseded"

        # No existing memory -> create a new one.
        self.conn.execute("""
            INSERT INTO memories(
                category,
                subject,
                predicate,
                value,
                confidence,
                status,
                created_at,
                updated_at,
                source_text
            )
            VALUES(?,?,?,?,?,'active',?,?,?)
        """, (
            category,
            subject,
            predicate,
            value,
            confidence,
            now(),
            now(),
            source_text,
        ))
        self.conn.commit()

        return self.conn.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0], "created"

    def active_memories(self):
        return [dict(r) for r in self.conn.execute("""
            SELECT * FROM memories
            WHERE status='active'
            ORDER BY updated_at DESC
        """).fetchall()]

    def decay_memories(self, days=30, decay_rate=0.05, minimum_confidence=0.35):
        """
        Gradually reduce confidence for memories that have not been
        accessed or refreshed for a long time.

        Decay is applied once per elapsed decay period.
        The decay timestamp is kept separate from updated_at so that
        confidence decay does not refresh the memory itself.
        """

        rows = self.conn.execute("""
            SELECT
                id,
                confidence,
                updated_at,
                last_accessed_at,
                last_decayed_at
            FROM memories
            WHERE status='active'
        """).fetchall()

        now_dt = datetime.now(timezone.utc)

        for row in rows:
            reference_time = (
                row["last_accessed_at"]
                or row["updated_at"]
            )

            try:
                reference_dt = datetime.fromisoformat(reference_time)
            except (TypeError, ValueError):
                continue

            # If this memory has never been decayed, calculate from
            # its last refresh/access time.
            decay_reference = row["last_decayed_at"]

            if decay_reference:
                try:
                    decay_dt = datetime.fromisoformat(decay_reference)
                except (TypeError, ValueError):
                    decay_dt = reference_dt
            else:
                decay_dt = reference_dt

            age_days = (
                now_dt - decay_dt
            ).total_seconds() / 86400

            if age_days < days:
                continue

            decay_periods = int(age_days // days)

            new_confidence = max(
                minimum_confidence,
                float(row["confidence"])
                - (decay_rate * decay_periods),
            )

            if new_confidence < float(row["confidence"]):
                self.conn.execute("""
                    UPDATE memories
                    SET
                        confidence=?,
                        last_decayed_at=?
                    WHERE id=?
                """, (
                    new_confidence,
                    now(),
                    row["id"],
                ))

        self.conn.commit()

    def historical_employers(self):
        rows = self.conn.execute("""
            SELECT *
            FROM memories
            WHERE category='work'
            AND predicate='previous_employer'
            AND status='active'
            ORDER BY created_at DESC
        """).fetchall()

        return [dict(row) for row in rows]

    def mark_accessed(self, ids):
        if not ids:
            return
        stamp = now()
        self.conn.executemany(
            "UPDATE memories SET last_accessed_at=? WHERE id=?",
            [(stamp, i) for i in ids]
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
