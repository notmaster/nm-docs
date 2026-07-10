from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from nmv6.evidence import EvidenceStore
from nmv6.reducer import Reducer
from nmv6.store import Store


class CrashRecoveryAcceptanceTests(unittest.TestCase):
    def child(self, script: str, *, failpoint: str) -> subprocess.CompletedProcess[str]:
        environment = {
            **os.environ,
            "PYTHONPATH": str(TOOLS_ROOT),
            "NM_V6_FAILPOINT": failpoint,
            "NM_V6_FAILPOINT_ACTION": "sigkill",
        }
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(script)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_ac017_state_sigkill_matrix_has_one_logical_effect(self) -> None:
        points = (
            "state.before_begin",
            "state.after_begin",
            "state.after_event_insert",
            "state.after_audit_outbox_insert",
            "state.before_commit",
            "state.after_commit",
        )
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "state.sqlite3"
                Store(database).close()
                result = self.child(
                    f"""
                    from pathlib import Path
                    from nmv6.store import Store
                    from nmv6.reducer import Reducer
                    store = Store(Path({str(database)!r}))
                    Reducer(store).create_run(
                        run_id='run-crash', spec_hash='a'*64, config_hash='b'*64,
                        idempotency_key='create-run-crash')
                    """,
                    failpoint=point,
                )
                self.assertIn(result.returncode, {-9, 137})
                store = Store(database)
                try:
                    store.integrity_check()
                    reducer = Reducer(store)
                    replay = reducer.create_run(
                        run_id="run-crash",
                        spec_hash="a" * 64,
                        config_hash="b" * 64,
                        idempotency_key="create-run-crash",
                    )
                    self.assertEqual(replay["run_id"], "run-crash")
                    self.assertEqual(len(store.list_events(run_id="run-crash")), 1)
                    self.assertEqual(len(store.list_audit()), 1)
                finally:
                    store.close()

    def test_ac058_blob_and_receipt_sigkill_boundaries_are_recoverable(self) -> None:
        blob_points = (
            "evidence.before_blob_write",
            "evidence.after_blob_write",
            "evidence.after_blob_fsync",
            "evidence.before_blob_rename",
            "evidence.after_blob_rename",
            "evidence.after_directory_fsync",
        )
        receipt_points = (
            "evidence.before_receipt_insert",
            "evidence.after_receipt_insert",
        )
        script = """
            import sys
            from pathlib import Path
            from nmv6.store import Store
            from nmv6.reducer import Reducer
            from nmv6.evidence import EvidenceStore
            from nmv6.util import utc_now
            root = Path(sys.argv[1])
            store = Store(root / 'state.sqlite3')
            evidence = EvidenceStore(root / 'evidence')
            receipt = {
                'evidence_id':'EVID-run-001','evidence_type':'command_result',
                'producer':'nm-v6-core/gate-executor','run_id':'run-crash',
                'subject_ids':['TASK-001'],'assertions':{},
                'spec_hash':'a'*64,'config_hash':'b'*64,
                'source_commit':None,'candidate_commit':'candidate',
                'release_source_kind':None,'release_source_commit':None,
                'release_source_tree':None,'hotfix_reconciliation_gate_id':None,
                'artifact_digest':None,'environment_id':None,
                'environment_fingerprint':None,'operation_id':None,
                'attempt_id':'ATTEMPT-run-001','command_action_id':'task_verify',
                'argv_digest':'c'*64,'working_directory':'.','started_at':utc_now(),
                'finished_at':utc_now(),'exit_code':0,'result':'passed',
                'stdout_digest':None,'stderr_digest':None,
                'tool_versions':{'python':sys.version.split()[0]},
                'producer_version':'test-v1','evaluator_version':'test-v1',
                'redaction_version':'placeholder'}
            receipt = evidence.persist(receipt, b'passed', b'')
            Reducer(store, evidence_store=evidence).record_evidence(
                run_id='run-crash', expected_revision=0, receipt=receipt,
                idempotency_key='record-evidence')
        """
        for point in (*blob_points, *receipt_points):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = Store(root / "state.sqlite3")
                Reducer(store).create_run(
                    run_id="run-crash",
                    spec_hash="a" * 64,
                    config_hash="b" * 64,
                    idempotency_key="create-run",
                )
                store.close()
                environment = {
                    **os.environ,
                    "PYTHONPATH": str(TOOLS_ROOT),
                    "NM_V6_FAILPOINT": point,
                    "NM_V6_FAILPOINT_ACTION": "sigkill",
                }
                result = subprocess.run(
                    [sys.executable, "-c", textwrap.dedent(script), str(root)],
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertIn(result.returncode, {-9, 137})
                store = Store(root / "state.sqlite3")
                evidence = EvidenceStore(root / "evidence")
                try:
                    store.integrity_check()
                    receipt = store.get_evidence("EVID-run-001")
                    if receipt is not None:
                        evidence.validate(receipt)
                        self.assertEqual(len(store.list_evidence("run-crash")), 1)
                    else:
                        evidence.quarantine_orphans(store.referenced_evidence_digests())
                        self.assertEqual(store.list_evidence("run-crash"), [])
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
