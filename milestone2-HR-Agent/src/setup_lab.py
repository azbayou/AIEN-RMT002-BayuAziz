from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from psycopg.types.json import Jsonb

from .config import get_settings
from .providers import DeterministicProvider, OpenAIProvider
from .security import connect_db, hash_password, token_hash

ROOT = Path(__file__).resolve().parents[1]


def chunk_policy(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"policy {path} is missing front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError(f"policy {path} has incomplete front matter") from error

    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            raise ValueError(f"invalid front matter in {path}")
        metadata[key.strip()] = value.strip()
    required = ("document_id", "title", "version", "effective_date")
    if any(field not in metadata for field in required):
        raise ValueError(f"policy {path} is missing required metadata")

    chunks: list[dict[str, str]] = []
    current_section: str | None = None
    content: list[str] = []

    def append_chunk() -> None:
        if current_section is None:
            return
        text = "\n".join(content).strip()
        if not text:
            return
        identity = "\n".join(
            (metadata["document_id"], metadata["version"], current_section, text)
        )
        chunks.append(
            {
                "chunk_id": f"{metadata['document_id']}:{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
                "document_id": metadata["document_id"],
                "title": metadata["title"],
                "section": current_section,
                "version": metadata["version"],
                "effective_date": metadata["effective_date"],
                "content": text,
            }
        )

    for line in lines[end + 1 :]:
        if line.startswith("## "):
            append_chunk()
            current_section = line[3:].strip()
            content = []
        elif current_section is not None:
            content.append(line)
    append_chunk()
    if not chunks:
        raise ValueError(f"policy {path} has no non-empty sections")
    return chunks


def reset_and_seed(reset: bool = False) -> None:
    settings = get_settings()
    employees = json.loads((ROOT / "data" / "employees.json").read_text(encoding="utf-8"))
    policies = [
        chunk
        for path in sorted((ROOT / "data" / "policies").glob("*.md"))
        for chunk in chunk_policy(path)
    ]

    with connect_db(settings.database_url) as connection:
        with connection.cursor() as cursor:
            if reset:
                cursor.execute(
                    "DROP TABLE IF EXISTS proposal_attachments, auth_sessions, evaluation_cases, "
                    "leave_attachments, approval_audit_logs, traces, tickets, leave_requests, action_proposals, "
                    "policy_chunks, leave_balances, persona_tokens, medical_terms, monitoring_rules, employees CASCADE"
                )
            cursor.execute("DROP TABLE IF EXISTS persona_tokens CASCADE")
            dimension = settings.embedding_dimensions
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    username TEXT UNIQUE,
                    password_hash TEXT,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('employee', 'manager', 'monitoring_admin')),
                    department TEXT,
                    manager_id TEXT,
                    token_hash TEXT NOT NULL UNIQUE
                );
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS username TEXT UNIQUE;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS password_hash TEXT;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS department TEXT;
                ALTER TABLE employees ADD COLUMN IF NOT EXISTS manager_id TEXT;
                ALTER TABLE employees DROP CONSTRAINT IF EXISTS employees_role_check;
                ALTER TABLE employees ADD CONSTRAINT employees_role_check
                    CHECK (role IN ('employee', 'manager', 'monitoring_admin'));
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_token_hash TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_employee_idx
                    ON auth_sessions (employee_id, expires_at);
                CREATE TABLE IF NOT EXISTS leave_balances (
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    leave_type TEXT NOT NULL,
                    available_days INTEGER NOT NULL CHECK (available_days >= 0),
                    as_of_date DATE NOT NULL,
                    PRIMARY KEY (employee_id, leave_type)
                );
                CREATE TABLE IF NOT EXISTS medical_terms (
                    term TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS monitoring_rules (
                    rule_id TEXT PRIMARY KEY,
                    metric TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    threshold DOUBLE PRECISION NOT NULL,
                    minimum_samples INTEGER NOT NULL DEFAULT 1,
                    owner TEXT NOT NULL,
                    response TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evaluation_cases (
                    case_id TEXT PRIMARY KEY,
                    sort_order INTEGER NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policy_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    section TEXT NOT NULL,
                    version TEXT NOT NULL,
                    effective_date DATE NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({dimension}) NOT NULL
                );
                CREATE INDEX IF NOT EXISTS policy_chunks_document_idx
                    ON policy_chunks (document_id, version);
                CREATE INDEX IF NOT EXISTS policy_chunks_fts_idx
                    ON policy_chunks USING GIN (to_tsvector('simple', title || ' ' || section || ' ' || content));
                CREATE TABLE IF NOT EXISTS action_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    action_type TEXT NOT NULL,
                    leave_type TEXT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    business_days INTEGER NOT NULL CHECK (business_days > 0),
                    reason TEXT,
                    validation_summary TEXT[] NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    requires_attachment BOOLEAN DEFAULT FALSE
                );
                ALTER TABLE action_proposals ADD COLUMN IF NOT EXISTS requires_attachment BOOLEAN DEFAULT FALSE;
                CREATE INDEX IF NOT EXISTS action_proposals_employee_idx
                    ON action_proposals (employee_id, expires_at);
                CREATE TABLE IF NOT EXISTS proposal_attachments (
                    proposal_id TEXT PRIMARY KEY REFERENCES action_proposals(proposal_id) ON DELETE CASCADE,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'image/png', 'image/jpeg')),
                    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes > 0 AND file_size_bytes <= 5242880),
                    file_bytes BYTEA NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS leave_requests (
                    request_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE REFERENCES action_proposals(proposal_id),
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    leave_type TEXT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    business_days INTEGER NOT NULL CHECK (business_days > 0),
                    status TEXT NOT NULL DEFAULT 'pending_manager_review'
                        CHECK (status IN ('pending_manager_review', 'approved', 'rejected', 'cancelled')),
                    idempotency_key TEXT NOT NULL,
                    reviewed_by TEXT REFERENCES employees(employee_id),
                    review_note TEXT,
                    reviewed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (employee_id, idempotency_key)
                );
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS reviewed_by TEXT;
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS review_note TEXT;
                ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
                ALTER TABLE leave_requests DROP CONSTRAINT IF EXISTS leave_requests_status_check;
                ALTER TABLE leave_requests ADD CONSTRAINT leave_requests_status_check
                    CHECK (status IN ('pending_manager_review', 'approved', 'rejected', 'cancelled'));

                CREATE TABLE IF NOT EXISTS approval_audit_logs (
                    audit_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL REFERENCES leave_requests(request_id),
                    reviewer_id TEXT NOT NULL REFERENCES employees(employee_id),
                    previous_status TEXT NOT NULL,
                    new_status TEXT NOT NULL CHECK (new_status IN ('approved', 'rejected')),
                    review_note TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS leave_attachments (
                    request_id TEXT PRIMARY KEY REFERENCES leave_requests(request_id) ON DELETE CASCADE,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'image/png', 'image/jpeg')),
                    file_size_bytes INTEGER NOT NULL CHECK (file_size_bytes > 0 AND file_size_bytes <= 5242880),
                    file_bytes BYTEA NOT NULL,
                    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS leave_requests_employee_dates_idx
                    ON leave_requests (employee_id, start_date, end_date);
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'on progress', 'done')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ,
                    updated_by TEXT REFERENCES employees(employee_id)
                );
                ALTER TABLE tickets ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
                ALTER TABLE tickets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
                ALTER TABLE tickets ADD COLUMN IF NOT EXISTS updated_by TEXT REFERENCES employees(employee_id);
                ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_status_check;
                ALTER TABLE tickets ADD CONSTRAINT tickets_status_check CHECK (status IN ('pending', 'on progress', 'done'));
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS traces_employee_idx
                    ON traces (employee_id, created_at);
                """
            )
            if dimension <= 2000:
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS policy_chunks_embedding_hnsw_idx "
                    "ON policy_chunks USING hnsw (embedding vector_cosine_ops)"
                )
            valid_emp_ids = [e["employee_id"] for e in employees]
            if valid_emp_ids:
                cursor.execute(
                    "SELECT COUNT(*) FROM employees WHERE NOT (employee_id = ANY(%s::text[]))",
                    (valid_emp_ids,),
                )
                stale_count = cursor.fetchone()[0]
                if reset or stale_count > 0:
                    cursor.execute(
                        "UPDATE employees SET manager_id = NULL "
                        "WHERE manager_id IS NOT NULL AND NOT (manager_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "UPDATE leave_requests SET reviewed_by = NULL "
                        "WHERE reviewed_by IS NOT NULL AND NOT (reviewed_by = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "UPDATE tickets SET updated_by = NULL "
                        "WHERE updated_by IS NOT NULL AND NOT (updated_by = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM approval_audit_logs "
                        "WHERE NOT (reviewer_id = ANY(%s::text[])) "
                        "OR request_id IN (SELECT request_id FROM leave_requests WHERE NOT (employee_id = ANY(%s::text[])))",
                        (valid_emp_ids, valid_emp_ids),
                    )
                    cursor.execute(
                        "DELETE FROM leave_attachments "
                        "WHERE NOT (employee_id = ANY(%s::text[])) "
                        "OR request_id IN (SELECT request_id FROM leave_requests WHERE NOT (employee_id = ANY(%s::text[])))",
                        (valid_emp_ids, valid_emp_ids),
                    )
                    cursor.execute(
                        "DELETE FROM proposal_attachments "
                        "WHERE NOT (employee_id = ANY(%s::text[])) "
                        "OR proposal_id IN (SELECT proposal_id FROM action_proposals WHERE NOT (employee_id = ANY(%s::text[])))",
                        (valid_emp_ids, valid_emp_ids),
                    )
                    cursor.execute(
                        "DELETE FROM leave_requests WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM action_proposals WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM auth_sessions WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM leave_balances WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM tickets WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM traces WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )
                    cursor.execute(
                        "DELETE FROM employees WHERE NOT (employee_id = ANY(%s::text[]))",
                        (valid_emp_ids,),
                    )

            cursor.execute("SELECT COUNT(*) FROM employees")
            emp_count = cursor.fetchone()[0]
            if emp_count == 0 or reset:
                for employee in employees:
                    username = employee.get("username") or employee["employee_id"].lower()
                    raw_password = employee.get("password", "Password#123")
                    pwd_hash = hash_password(raw_password)
                    cursor.execute(
                        """
                        INSERT INTO employees
                            (employee_id, username, password_hash, display_name, role, department, manager_id, token_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (employee_id) DO UPDATE SET
                            username = EXCLUDED.username,
                            password_hash = EXCLUDED.password_hash,
                            display_name = EXCLUDED.display_name,
                            role = EXCLUDED.role,
                            department = EXCLUDED.department,
                            manager_id = EXCLUDED.manager_id,
                            token_hash = EXCLUDED.token_hash
                        """,
                        (
                            employee["employee_id"],
                            username,
                            pwd_hash,
                            employee["display_name"],
                            employee["role"],
                            employee.get("department"),
                            employee.get("manager_id"),
                            token_hash(employee["token"]),
                        ),
                    )
                    for leave_type, available_days in employee.get("balances", {}).items():
                        cursor.execute(
                            """
                            INSERT INTO leave_balances (employee_id, leave_type, available_days, as_of_date)
                            VALUES (%s, %s, %s, CURRENT_DATE)
                            ON CONFLICT (employee_id, leave_type) DO UPDATE SET
                                available_days = EXCLUDED.available_days,
                                as_of_date = EXCLUDED.as_of_date
                            """,
                            (employee["employee_id"], leave_type, available_days),
                        )

                hist_path = ROOT / "data" / "historical_requests.json"
                if hist_path.is_file():
                    historical_requests = json.loads(hist_path.read_text(encoding="utf-8"))
                    for req in historical_requests:
                        if valid_emp_ids and req["employee_id"] not in valid_emp_ids:
                            continue
                        proposal_id = req["request_id"]
                        cursor.execute(
                            """
                            INSERT INTO action_proposals
                                (proposal_id, employee_id, action_type, leave_type, start_date, end_date,
                                 business_days, reason, validation_summary, expires_at, requires_attachment)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (proposal_id) DO NOTHING
                            """,
                            (
                                proposal_id,
                                req["employee_id"],
                                "leave_request",
                                req["leave_type"],
                                req["start_date"],
                                req["end_date"],
                                req["business_days"],
                                req.get("reason"),
                                req.get("validation_summary", ["Historical seed record"]),
                                req.get("expires_at") or req["created_at"],
                                False,
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT INTO leave_requests
                                (request_id, proposal_id, employee_id, leave_type, start_date, end_date,
                                 business_days, status, idempotency_key, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (
                                req["request_id"],
                                proposal_id,
                                req["employee_id"],
                                req["leave_type"],
                                req["start_date"],
                                req["end_date"],
                                req["business_days"],
                                req["status"],
                                f"seed-{req['request_id']}",
                                req["created_at"],
                            ),
                        )

            med_terms_path = ROOT / "data" / "medical_terms.json"
            if med_terms_path.is_file():
                try:
                    med_terms = json.loads(med_terms_path.read_text(encoding="utf-8"))
                    for term in med_terms:
                        cursor.execute(
                            """
                            INSERT INTO medical_terms (term)
                            VALUES (%s)
                            ON CONFLICT (term) DO NOTHING
                            """,
                            (term,),
                        )
                except Exception:
                    pass

            mon_rules_path = ROOT / "data" / "monitoring_rules.json"
            if mon_rules_path.is_file():
                try:
                    mon_rules = json.loads(mon_rules_path.read_text(encoding="utf-8"))
                    for r in mon_rules:
                        cursor.execute(
                            """
                            INSERT INTO monitoring_rules
                                (rule_id, metric, operator, threshold, minimum_samples, owner, response)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (rule_id) DO NOTHING
                            """,
                            (
                                r["rule_id"],
                                r["metric"],
                                r.get("operator", "gt"),
                                float(r["threshold"]),
                                int(r.get("minimum_samples", 1)),
                                r.get("owner", "AI Platform"),
                                r.get("response", ""),
                            ),
                        )
                except Exception:
                    pass

            eval_cases_path = ROOT / "data" / "evaluation_cases.json"
            if eval_cases_path.is_file():
                eval_cases = json.loads(eval_cases_path.read_text(encoding="utf-8"))
                valid_case_ids = [item["case_id"] for item in eval_cases if item.get("case_id")]
                if valid_case_ids:
                    cursor.execute(
                        "DELETE FROM evaluation_cases WHERE NOT (case_id = ANY(%s::text[]))",
                        (valid_case_ids,),
                    )
                for idx, item in enumerate(eval_cases):
                    cursor.execute(
                        """
                        INSERT INTO evaluation_cases (case_id, sort_order, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (case_id) DO UPDATE SET
                            sort_order = EXCLUDED.sort_order,
                            payload = EXCLUDED.payload
                        """,
                        (item["case_id"], idx, Jsonb(item)),
                    )

            provider = (
                OpenAIProvider(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.agent_model,
                    embedding_model=settings.embedding_model,
                    timeout=settings.model_timeout_seconds,
                )
                if settings.live_model_ready
                else DeterministicProvider(dimension)
            )
            embeddings = provider.embed(
                [f"{chunk['title']} - {chunk['section']}\n{chunk['content']}" for chunk in policies]
            )
            if any(len(vector) != dimension for vector in embeddings):
                raise ValueError("embedding dimensions do not match EMBEDDING_DIMENSIONS")

            valid_chunk_ids = [chunk["chunk_id"] for chunk in policies]
            cursor.execute(
                "DELETE FROM policy_chunks WHERE NOT (chunk_id = ANY(%s::text[]))",
                (valid_chunk_ids,),
            )

            for chunk, embedding in zip(policies, embeddings):
                cursor.execute(
                    """
                    INSERT INTO policy_chunks
                        (chunk_id, document_id, title, section, version, effective_date, content, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        title = EXCLUDED.title,
                        section = EXCLUDED.section,
                        version = EXCLUDED.version,
                        effective_date = EXCLUDED.effective_date,
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding
                    """,
                    (
                        chunk["chunk_id"],
                        chunk["document_id"],
                        chunk["title"],
                        chunk["section"],
                        chunk["version"],
                        chunk["effective_date"],
                        chunk["content"],
                        embedding,
                    ),
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed HR assistant policy and demo data")
    parser.add_argument("--reset", action="store_true", help="drop and recreate seed tables")
    reset_and_seed(reset=parser.parse_args().reset)
