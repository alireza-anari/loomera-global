"""Phase 7.33 static CI-only ACL fixture boundary guards."""
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class Phase733FixtureBoundaryTests(SimpleTestCase):
    def test_runner_requires_grant_and_refuses_existing_resources(self):
        runner = (
            ROOT / "tests/phase7_redis_role_acl_ci.sh"
        ).read_text(encoding="utf-8")
        for required in (
            "GITHUB_ACTIONS", "LOOMERA_PHASE733_TEST_REDIS",
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT",
            "docker container inspect", "127.0.0.1:6433",
            "owned=0", "trap cleanup EXIT", "redis:7.4-alpine",
            "phase7_redis_role_acl_test.py",
        ):
            self.assertIn(required, runner)
        self.assertNotIn("docker volume create", runner)
        self.assertNotIn("0.0.0.0:6433", runner)

    def test_physical_tests_are_disposable_and_dangerous_checks_use_dryrun(self):
        physical = (
            ROOT / "tests/phase7_redis_role_acl_test.py"
        ).read_text(encoding="utf-8")
        for expected in (
            "PORT = 6433", "DB = 15",
            "loomera:api-auth-otp-cache", '"ACL", "DRYRUN"',
            "phase733_overbroad", "self.admin.delete(*self.keys.values())",
        ):
            self.assertIn(expected, physical)
        self.assertNotIn("flushall(", physical.lower())
        self.assertNotIn("flushdb(", physical.lower())
        self.assertNotIn('os.environ.get("CACHE_LOCATION")', physical)
        self.assertNotIn('os.environ.get("CELERY_BROKER_URL")', physical)

    def test_ci_opt_in_and_release_blocked_docs(self):
        ci = (
            ROOT / ".github/workflows/ci.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('LOOMERA_PHASE733_TEST_REDIS: "1"', ci)
        self.assertIn("bash tests/phase7_redis_role_acl_ci.sh", ci)
        doc = (
            ROOT / "docs/globalization/PHASE7_33_PHYSICAL_REDIS_ACL.md"
        ).read_text(encoding="utf-8")
        matrix = (
            ROOT / "docs/globalization/PHASE7_33_EXIT_MATRIX.json"
        ).read_text(encoding="utf-8")
        for evidence in (doc, matrix):
            self.assertIn("BLOCKED", evidence)
            self.assertNotIn("PRODUCTION_APPROVED", evidence)
