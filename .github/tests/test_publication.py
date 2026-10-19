"""Fork-owned publication contract; no Google or dispatch credentials required."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SHARED = "Serph91P/repository.serph91p/.github/workflows/"
SOURCE = "Serph91P/plugin.video.youtube"
HEAD = "a" * 40


def workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


class PublicationContractTests(unittest.TestCase):
    def test_existing_validation_identity_and_upstream_guard_are_retained(self):
        config = workflow("addon-validations.yml")
        self.assertEqual(config["name"], "Add-on Validations")
        self.assertEqual(
            config["jobs"]["addon-validations"]["if"],
            "github.repository == 'anxdpanic/plugin.video.youtube'",
        )
        self.assertIn("master", config["on"]["push"]["branches"])
        self.assertIn("master", config["on"]["pull_request"]["branches"])
        self.assertIn("workflow_dispatch", config["on"])

    def test_fork_package_requires_profile_and_source_contract_tests(self):
        jobs = workflow("addon-validations.yml")["jobs"]
        tests = jobs["fork-tests"]
        self.assertIn(f"github.repository == '{SOURCE}'", tests["if"])
        self.assertIn("github.ref == 'refs/heads/master'", tests["if"])
        self.assertIn("github.event_name == 'pull_request'", tests["if"])
        commands = "\n".join(step.get("run", "") for step in tests["steps"])
        self.assertIn("python -m unittest discover -s tests -v", commands)
        self.assertIn("python -m unittest discover -s .github/tests -v", commands)
        self.assertIn("PyYAML==6.0.3", commands)
        package = jobs["fork-package"]
        self.assertEqual(package["needs"], "fork-tests")
        self.assertRegex(
            package["uses"], "^" + re.escape(SHARED)
            + r"reusable-addon-package\.yml@[0-9a-f]{40}$",
        )
        self.assertEqual(package["with"]["addon_id"], "plugin.video.youtube")
        self.assertEqual(
            json.loads(package["with"]["runtime_entries_json"]),
            ["addon.xml", "changelog.txt", "LICENSES/", "resources/"],
        )
        self.assertEqual(
            package["permissions"], {"contents": "read", "id-token": "write"}
        )

    def test_notifier_only_accepts_completed_master_validation(self):
        config = workflow("notify-repository.yml")
        self.assertEqual(set(config["on"]), {"workflow_run"})
        self.assertEqual(config["on"]["workflow_run"], {
            "workflows": ["Add-on Validations"],
            "types": ["completed"], "branches": ["master"],
        })
        job = config["jobs"]["validate-evidence"]
        for guard in (
            f"github.repository == '{SOURCE}'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.event == 'workflow_dispatch'",
            "github.event.workflow_run.head_branch == 'master'",
        ):
            self.assertIn(guard, job["if"])
        self.assertNotIn("secrets.", json.dumps(job))
        self.assertEqual(job["permissions"], {"actions": "read"})

    def test_notifier_is_pinned_and_forwards_only_the_canonical_identity(self):
        job = workflow("notify-repository.yml")["jobs"]["notify"]
        self.assertEqual(job["needs"], "validate-evidence")
        self.assertRegex(
            job["uses"], "^" + re.escape(SHARED)
            + r"reusable-notify-repository\.yml@[0-9a-f]{40}$",
        )
        inputs = job["with"]
        self.assertEqual(inputs["expected_branch"], "master")
        self.assertEqual(inputs["addon_id"], "plugin.video.youtube")
        self.assertEqual(inputs["validation_workflow"], "Add-on Validations")
        self.assertEqual(inputs["validation_workflow_path"], ".github/workflows/addon-validations.yml")
        self.assertEqual(inputs["candidate_sha"], "${{ github.event.workflow_run.head_sha }}")
        self.assertEqual(inputs["validation_run_id"], "${{ github.event.workflow_run.id }}")
        self.assertEqual(job["secrets"], {
            "REPO_DISPATCH_TOKEN": "${{ secrets.REPO_DISPATCH_TOKEN }}"
        })
        self.assertNotIn("SOURCE_ARTIFACT_TOKEN", json.dumps(job))

    def run_evidence(self, value):
        steps = workflow("notify-repository.yml")["jobs"]["validate-evidence"]["steps"]
        block = next(step["run"] for step in steps if step.get("id") == "evidence")
        script = block.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "validation-evidence.json").write_text(
                value if isinstance(value, str) else json.dumps(value), encoding="utf-8"
            )
            output = root / "outputs"
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=root,
                env={"RUN_ID": "123", "RUN_HEAD_SHA": HEAD, "GITHUB_OUTPUT": str(output)},
                capture_output=True, text=True, check=False,
            )
            return result, output.read_text() if output.exists() else ""

    @staticmethod
    def evidence():
        return {
            "validation_run_id": 123, "candidate_sha": HEAD,
            "validation_head_sha": HEAD, "addon_id": "plugin.video.youtube",
            "addon_version": "7.4.4", "asset_name": "plugin.video.youtube-7.4.4.zip",
            "artifact_sha256": "b" * 64, "publication_id": "plugin.video.youtube@7.4.4",
        }

    def test_valid_evidence_produces_only_package_outputs(self):
        result, output = self.run_evidence(self.evidence())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(line.split("=", 1)[0] for line in output.splitlines()), {
            "addon_version", "asset_name", "artifact_sha256", "publication_id",
        })

    def test_invalid_evidence_never_produces_outputs(self):
        cases = (
            {"validation_run_id": "123"}, {"candidate_sha": "c" * 40},
            {"validation_head_sha": "c" * 40}, {"addon_id": "script.tubecast"},
            {"addon_version": "7.4.4\n"}, {"asset_name": "wrong.zip"},
            {"artifact_sha256": "b" * 64 + "\n"}, {"publication_id": "other@7.4.4"},
        )
        for changed in cases:
            with self.subTest(changed=changed):
                value = self.evidence()
                value.update(changed)
                result, output = self.run_evidence(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(output, "")
        duplicate = json.dumps(self.evidence())[:-1] + ', "addon_id": "plugin.video.youtube"}'
        result, output = self.run_evidence(duplicate)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
