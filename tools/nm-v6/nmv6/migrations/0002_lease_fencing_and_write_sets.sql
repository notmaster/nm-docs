CREATE TABLE lease_fencing_counters (
    resource_id TEXT PRIMARY KEY,
    last_fencing_token INTEGER NOT NULL CHECK (last_fencing_token > 0)
);

ALTER TABLE leases ADD COLUMN write_set_json TEXT NOT NULL DEFAULT '[]';

CREATE TRIGGER lease_fencing_counters_no_delete
BEFORE DELETE ON lease_fencing_counters
BEGIN
    SELECT RAISE(ABORT, 'lease fencing counters are monotonic');
END;
