#!/usr/bin/env python3
"""Prepare and verify a release-based upstream merge without changing master."""

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class CandidateResult:
    status: str
    branch: str
    target_sha: str
    release_sha: str
    candidate_sha: str = ""


def git(repo, *args, check=True, env=None):
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )


def update_branch(release_tag, release_sha):
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", release_tag).strip(".-") or "release"
    return "automation/upstream-release-{}-{}".format(safe_tag, release_sha[:12])


def should_open_pull_request(branch, open_pr_heads):
    return branch not in set(open_pr_heads)


def prepare_candidate(repo, target, release_sha, release_tag):
    repo = Path(repo)
    target_sha = git(repo, "rev-parse", target).stdout.strip()
    branch = update_branch(release_tag, release_sha)
    integrated = git(repo, "merge-base", "--is-ancestor", release_sha, target, check=False)
    if integrated.returncode == 0:
        return CandidateResult("integrated", branch, target_sha, release_sha)

    git(repo, "checkout", "-B", branch, target)
    # Stable commit metadata permits a safe retry after push succeeded but PR
    # creation failed. A retry can reuse the same branch without force-pushing.
    environment = dict(os.environ)
    stamp = git(repo, 'show', '-s', '--format=%cI', target_sha).stdout.strip()
    environment.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    merge = git(repo, "-c", "user.name=upstream-release-update", "-c",
                "user.email=upstream-release-update@users.noreply.github.com",
                "merge", "--no-ff", "--no-edit", release_sha, check=False, env=environment)
    if merge.returncode:
        git(repo, "merge", "--abort", check=False)
        return CandidateResult("conflict", branch, target_sha, release_sha)
    candidate_sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    return CandidateResult("ready", branch, target_sha, release_sha, candidate_sha)


def verify_candidate(repo, target, release_sha, candidate_sha):
    repo = Path(repo)
    target_sha = git(repo, "rev-parse", target).stdout.strip()
    parents = git(repo, "show", "-s", "--format=%P", candidate_sha).stdout.split()
    if len(parents) != 2 or parents[0] != target_sha or parents[1] != release_sha:
        raise ValueError("candidate is not a merge of the unchanged target and exact release commit")
    # Parent IDs alone do not constrain a commit's tree. Candidate tests run
    # untrusted code and could forge the uploaded bundle or metadata.
    expected = git(repo, 'merge-tree', '--write-tree', target_sha, release_sha, check=False)
    actual_tree = git(repo, 'rev-parse', candidate_sha + '^{tree}').stdout.strip()
    if expected.returncode or actual_tree != expected.stdout.splitlines()[0]:
        raise ValueError('candidate tree is not the independently reconstructed merge tree')
    return target_sha


def bundle_candidate(repo, branch, candidate_sha, output):
    if git(repo, 'rev-parse', branch).stdout.strip() != candidate_sha:
        raise ValueError('candidate branch moved before bundling')
    # A bundle needs an advertised ref, not just an unadvertised raw commit ID.
    git(repo, 'bundle', 'create', str(output), branch)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("candidate")
    candidate.add_argument("--repo", type=Path, required=True)
    candidate.add_argument("--target", required=True)
    candidate.add_argument("--release-sha", required=True)
    candidate.add_argument("--release-tag", required=True)
    candidate.add_argument("--output", type=Path, required=True)
    bundle = commands.add_parser('bundle')
    bundle.add_argument('--repo', type=Path, required=True)
    bundle.add_argument('--branch', required=True)
    bundle.add_argument('--candidate-sha', required=True)
    bundle.add_argument('--output', type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--repo", type=Path, required=True)
    verify.add_argument("--target", required=True)
    verify.add_argument("--release-sha", required=True)
    verify.add_argument("--candidate-sha", required=True)
    args = parser.parse_args()

    if args.command == 'bundle':
        bundle_candidate(args.repo, args.branch, args.candidate_sha, args.output.resolve())
        return

    if args.command == "candidate":
        result = prepare_candidate(args.repo, args.target, args.release_sha, args.release_tag)
        args.output.write_text(json.dumps(asdict(result), sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(asdict(result), sort_keys=True))
        if result.status == "conflict":
            raise SystemExit("upstream release merge conflicts; master was not changed")
        return
    try:
        print(verify_candidate(args.repo, args.target, args.release_sha, args.candidate_sha))
    except ValueError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    main()
