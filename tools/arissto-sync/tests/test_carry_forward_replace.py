import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from arissto_sync.carry_forward_capture import sha256_file
from arissto_sync.carry_forward_plan import _canonical_hash
from arissto_sync.carry_forward_replace import _load_plan, _maintenance_url


class CarryForwardReplacementGuardsTests(unittest.TestCase):
    def test_reviewed_plan_rejects_changed_evidence_and_implementation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "carry-forward" / "evidence.json"
            evidence.parent.mkdir()
            evidence.write_text("original", encoding="utf-8")
            settings = SimpleNamespace(
                state_path=root / "state.sqlite3",
                target=SimpleNamespace(fingerprint="local-sandbox"),
            )
            plan = {
                "target": "sandbox:fineract_sandbox",
                "target_fingerprint": "local-sandbox",
                "evidence": {"sample": {"path": str(evidence), "sha256": sha256_file(evidence)}},
                "implementation_sha256": {},
            }

            def save_plan(document):
                digest = _canonical_hash(document)
                path = root / "carry-forward" / "plans" / f"{digest}.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({
                    "plan_hash": digest, "approved": False, "plan": document,
                }), encoding="utf-8")
                return digest

            digest = save_plan(plan)
            self.assertEqual(_load_plan(settings, digest), plan)
            cycle_settings = SimpleNamespace(
                state_path=root / "cycles" / "new-cycle" / "state.sqlite3",
                target=settings.target,
            )
            self.assertEqual(_load_plan(cycle_settings, digest), plan)
            evidence.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence changed"):
                _load_plan(settings, digest)

            evidence.write_text("original", encoding="utf-8")
            plan["implementation_sha256"] = {"carry_forward_replace.py": "0" * 64}
            changed_digest = save_plan(plan)
            with self.assertRaisesRegex(ValueError, "implementation changed"):
                _load_plan(settings, changed_digest)

    def test_database_swap_requires_local_registered_sandbox(self):
        def settings(url):
            return SimpleNamespace(target=SimpleNamespace(pg_url=url))

        local = "postgresql://operator@127.0.0.1:5432/fineract_sandbox"
        self.assertEqual(_maintenance_url(settings(local)),
                         "postgresql://operator@127.0.0.1:5432/postgres")
        for url in (
            local.replace("127.0.0.1", "database.example.com"),
            local.replace("fineract_sandbox", "default"),
        ):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "exact local sandbox"):
                _maintenance_url(settings(url))


if __name__ == "__main__":
    unittest.main()
