import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / ".scripts" / "upstream_release_update.py"
SPEC = importlib.util.spec_from_file_location("upstream_release_update", SCRIPT)
upstream_release_update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(upstream_release_update)


class ReleaseUpdateFixtures(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git_run("init")
        self.git_run("config", "user.name", "Test User")
        self.git_run("config", "user.email", "test@example.invalid")
        self.write("shared.txt", "base\n")
        self.commit("base")
        self.git_run("branch", "target")
        self.git_run("checkout", "-b", "upstream")

    def tearDown(self):
        self.tempdir.cleanup()

    def git_run(self, *args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=check,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write(self, name, content):
        (self.repo / name).write_text(content, encoding="utf-8")

    def commit(self, message):
        self.git_run("add", ".")
        self.git_run("commit", "-m", message)

    def test_clean_merge_preserves_fork_change(self):
        self.write("upstream.txt", "upstream release\n")
        self.commit("upstream release")
        release_sha = self.git_run("rev-parse", "HEAD").stdout.strip()
        self.git_run("checkout", "target")
        self.write("fork.txt", "keep this\n")
        self.commit("fork change")

        result = upstream_release_update.prepare_candidate(
            self.repo, "target", release_sha, "v1.2.3"
        )

        self.assertEqual("ready", result.status)
        self.assertTrue((self.repo / "fork.txt").exists())
        self.assertTrue((self.repo / "upstream.txt").exists())
        self.assertEqual(
            ["v1.2.3", release_sha[:12]], result.branch.rsplit("-", 2)[-2:]
        )
        self.assertEqual(2, len(self.git_run("show", "-s", "--format=%P", "HEAD").stdout.split()))

    def test_already_integrated_release_is_noop(self):
        self.write("upstream.txt", "upstream release\n")
        self.commit("upstream release")
        release_sha = self.git_run("rev-parse", "HEAD").stdout.strip()
        self.git_run("branch", "-f", "target", release_sha)

        result = upstream_release_update.prepare_candidate(
            self.repo, "target", release_sha, "v1.2.3"
        )

        self.assertEqual("integrated", result.status)
        self.assertEqual(release_sha, self.git_run("rev-parse", "target").stdout.strip())

    def test_conflict_leaves_target_unchanged(self):
        self.write("shared.txt", "upstream value\n")
        self.commit("upstream release")
        release_sha = self.git_run("rev-parse", "HEAD").stdout.strip()
        self.git_run("checkout", "target")
        self.write("shared.txt", "fork value\n")
        self.commit("fork change")
        target_sha = self.git_run("rev-parse", "target").stdout.strip()

        result = upstream_release_update.prepare_candidate(
            self.repo, "target", release_sha, "v1.2.3"
        )

        self.assertEqual("conflict", result.status)
        self.assertEqual(target_sha, self.git_run("rev-parse", "target").stdout.strip())
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())

    def test_retry_after_push_reuses_same_candidate_without_force(self):
        self.write('release.txt', 'upstream\n')
        self.commit('upstream release')
        release_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        self.git_run('checkout', 'target')
        remote = self.repo.parent / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        first = upstream_release_update.prepare_candidate(self.repo, 'target', release_sha, 'v1')
        self.git_run('push', str(remote), first.branch)
        second = upstream_release_update.prepare_candidate(self.repo, 'target', release_sha, 'v1')
        self.assertEqual(first.candidate_sha, second.candidate_sha)
        self.git_run('push', str(remote), second.branch)

    def test_verified_bundle_round_trip_preserves_exact_candidate(self):
        self.write('release.txt', 'upstream\n')
        self.commit('upstream release')
        release_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        self.git_run('checkout', 'target')
        result = upstream_release_update.prepare_candidate(self.repo, 'target', release_sha, 'v1')
        bundle = self.repo.parent / 'candidate.bundle'
        upstream_release_update.bundle_candidate(self.repo, result.branch, result.candidate_sha, bundle)
        clone = self.repo.parent / 'writer'
        subprocess.run(['git', 'clone', '--branch', 'target', str(self.repo), str(clone)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(clone), 'fetch', str(bundle),
                        result.candidate_sha + ':refs/automation/candidate'], check=True, capture_output=True)
        self.assertEqual(result.target_sha, upstream_release_update.verify_candidate(
            clone, 'target', release_sha, result.candidate_sha))

    def test_same_parent_merge_with_forged_tree_is_rejected(self):
        self.write('release.txt', 'upstream\n')
        self.commit('upstream release')
        release_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        self.git_run('checkout', 'target')
        target_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        result = upstream_release_update.prepare_candidate(self.repo, 'target', release_sha, 'v1')
        wrong_tree = self.git_run('rev-parse', 'target^{tree}').stdout.strip()
        forged = self.git_run('commit-tree', wrong_tree, '-p', target_sha, '-p', release_sha, '-m', 'forged').stdout.strip()
        with self.assertRaisesRegex(ValueError, 'tree'):
            upstream_release_update.verify_candidate(self.repo, 'target', release_sha, forged)

    def test_changed_target_and_wrong_release_are_rejected(self):
        self.write('release.txt', 'upstream\n')
        self.commit('upstream release')
        release_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        self.git_run('checkout', 'target')
        target_sha = self.git_run('rev-parse', 'HEAD').stdout.strip()
        result = upstream_release_update.prepare_candidate(self.repo, 'target', release_sha, 'v1')
        with self.assertRaises(ValueError):
            upstream_release_update.verify_candidate(self.repo, 'target', target_sha, result.candidate_sha)
        self.git_run('checkout', 'target')
        self.write('later.txt', 'new target\n')
        self.commit('target advanced')
        with self.assertRaises(ValueError):
            upstream_release_update.verify_candidate(self.repo, 'target', release_sha, result.candidate_sha)

    def test_existing_update_pull_request_is_deduplicated(self):
        branch = upstream_release_update.update_branch("v1.2.3", "a" * 40)

        self.assertTrue(upstream_release_update.should_open_pull_request(branch, []))
        self.assertFalse(upstream_release_update.should_open_pull_request(branch, [branch]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
