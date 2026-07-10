CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    digest TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE run_registry (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY REFERENCES run_registry(run_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    state TEXT NOT NULL,
    resume_state TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('staged', 'auto')),
    run_kind TEXT NOT NULL CHECK (run_kind IN ('normal', 'hotfix')),
    spec_hash TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE entity_states (
    machine TEXT NOT NULL CHECK (machine IN ('phase', 'task', 'attempt')),
    entity_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES run_registry(run_id),
    revision INTEGER NOT NULL CHECK (revision >= 0),
    state TEXT NOT NULL,
    resume_state TEXT,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (machine, entity_id)
);

CREATE TABLE events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    run_id TEXT REFERENCES run_registry(run_id),
    run_revision INTEGER,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    previous_digest TEXT NOT NULL,
    event_digest TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, idempotency_key)
);

CREATE TABLE idempotency_records (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idempotency_key)
);

CREATE TABLE immutable_records (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    run_id TEXT REFERENCES run_registry(run_id),
    record_digest TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
);

CREATE TABLE authorization_requests (
    request_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES run_registry(run_id),
    request_type TEXT NOT NULL,
    nonce TEXT NOT NULL UNIQUE,
    request_digest TEXT NOT NULL UNIQUE,
    expected_revision INTEGER,
    scope_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE authorization_records (
    authorization_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (
        record_type IN ('spec_confirmation', 'implementation_authorization', 'grant', 'approval', 'revocation')
    ),
    run_id TEXT REFERENCES run_registry(run_id),
    request_digest TEXT,
    nonce TEXT NOT NULL UNIQUE,
    authenticator_id TEXT NOT NULL,
    record_digest TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT,
    target_authorization_id TEXT REFERENCES authorization_records(authorization_id),
    created_at TEXT NOT NULL
);

CREATE TABLE authorization_uses (
    authorization_id TEXT NOT NULL REFERENCES authorization_records(authorization_id),
    operation_id TEXT NOT NULL,
    used_at TEXT NOT NULL,
    PRIMARY KEY (authorization_id, operation_id)
);

CREATE TABLE evidence_receipts (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_registry(run_id),
    evidence_type TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_json TEXT NOT NULL,
    stdout_digest TEXT,
    stderr_digest TEXT,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE gate_decisions (
    gate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_registry(run_id),
    gate_type TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('passed', 'failed', 'not_applicable')),
    run_revision INTEGER NOT NULL,
    decision_digest TEXT NOT NULL UNIQUE,
    decision_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE leases (
    resource_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_registry(run_id),
    owner TEXT NOT NULL,
    attempt_id TEXT,
    fencing_token INTEGER NOT NULL CHECK (fencing_token > 0),
    acquired_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE external_operations (
    operation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run_registry(run_id),
    action_id TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('planned', 'started', 'completed', 'not_started', 'partial', 'failed', 'unknown', 'cancelled')
    ),
    effect_id TEXT,
    authorization_id TEXT REFERENCES authorization_records(authorization_id),
    grant_revision INTEGER,
    fencing_token INTEGER,
    scope_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_records (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    run_id TEXT REFERENCES run_registry(run_id),
    run_revision INTEGER,
    previous_digest TEXT NOT NULL,
    event_digest TEXT NOT NULL,
    audit_digest TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE notification_outbox (
    notification_id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES run_registry(run_id),
    event_id TEXT NOT NULL REFERENCES events(event_id),
    route TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('progress', 'attention')),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivering', 'delivered', 'retry')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NOT NULL,
    delivered_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (route, event_id, severity)
);

CREATE INDEX events_run_sequence_idx ON events(run_id, sequence);
CREATE INDEX entity_states_run_idx ON entity_states(run_id, machine, state);
CREATE INDEX authorization_records_run_idx ON authorization_records(run_id, record_type);
CREATE INDEX evidence_receipts_run_idx ON evidence_receipts(run_id, evidence_type);
CREATE INDEX gate_decisions_run_idx ON gate_decisions(run_id, gate_type, run_revision);
CREATE INDEX external_operations_run_idx ON external_operations(run_id, status);
CREATE INDEX outbox_ready_idx ON notification_outbox(status, next_attempt_at);

CREATE TRIGGER schema_migrations_no_update
BEFORE UPDATE ON schema_migrations BEGIN SELECT RAISE(ABORT, 'schema migrations are append-only'); END;
CREATE TRIGGER schema_migrations_no_delete
BEFORE DELETE ON schema_migrations BEGIN SELECT RAISE(ABORT, 'schema migrations are append-only'); END;

CREATE TRIGGER run_registry_no_update
BEFORE UPDATE ON run_registry BEGIN SELECT RAISE(ABORT, 'run_registry is append-only'); END;
CREATE TRIGGER run_registry_no_delete
BEFORE DELETE ON run_registry BEGIN SELECT RAISE(ABORT, 'run_registry is append-only'); END;

CREATE TRIGGER events_no_update
BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER events_no_delete
BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER idempotency_no_update
BEFORE UPDATE ON idempotency_records BEGIN SELECT RAISE(ABORT, 'idempotency records are append-only'); END;
CREATE TRIGGER idempotency_no_delete
BEFORE DELETE ON idempotency_records BEGIN SELECT RAISE(ABORT, 'idempotency records are append-only'); END;

CREATE TRIGGER immutable_records_no_update
BEFORE UPDATE ON immutable_records BEGIN SELECT RAISE(ABORT, 'immutable records are append-only'); END;
CREATE TRIGGER immutable_records_no_delete
BEFORE DELETE ON immutable_records BEGIN SELECT RAISE(ABORT, 'immutable records are append-only'); END;

CREATE TRIGGER authorization_requests_no_update
BEFORE UPDATE ON authorization_requests BEGIN SELECT RAISE(ABORT, 'authorization requests are append-only'); END;
CREATE TRIGGER authorization_requests_no_delete
BEFORE DELETE ON authorization_requests BEGIN SELECT RAISE(ABORT, 'authorization requests are append-only'); END;

CREATE TRIGGER authorization_records_no_update
BEFORE UPDATE ON authorization_records BEGIN SELECT RAISE(ABORT, 'authorization records are append-only'); END;
CREATE TRIGGER authorization_records_no_delete
BEFORE DELETE ON authorization_records BEGIN SELECT RAISE(ABORT, 'authorization records are append-only'); END;

CREATE TRIGGER authorization_uses_no_update
BEFORE UPDATE ON authorization_uses BEGIN SELECT RAISE(ABORT, 'authorization uses are append-only'); END;
CREATE TRIGGER authorization_uses_no_delete
BEFORE DELETE ON authorization_uses BEGIN SELECT RAISE(ABORT, 'authorization uses are append-only'); END;

CREATE TRIGGER evidence_receipts_no_update
BEFORE UPDATE ON evidence_receipts BEGIN SELECT RAISE(ABORT, 'evidence receipts are append-only'); END;
CREATE TRIGGER evidence_receipts_no_delete
BEFORE DELETE ON evidence_receipts BEGIN SELECT RAISE(ABORT, 'evidence receipts are append-only'); END;

CREATE TRIGGER gate_decisions_no_update
BEFORE UPDATE ON gate_decisions BEGIN SELECT RAISE(ABORT, 'gate decisions are append-only'); END;
CREATE TRIGGER gate_decisions_no_delete
BEFORE DELETE ON gate_decisions BEGIN SELECT RAISE(ABORT, 'gate decisions are append-only'); END;

CREATE TRIGGER audit_records_no_update
BEFORE UPDATE ON audit_records BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
CREATE TRIGGER audit_records_no_delete
BEFORE DELETE ON audit_records BEGIN SELECT RAISE(ABORT, 'audit records are append-only'); END;
