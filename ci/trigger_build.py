#!/usr/bin/env python3
"""Trigger an ios-sweet XNU build with MACHINE_CONFIG=POLARIS.

You need either a fork of dipa-studio/ios-sweet with this repo's patches applied,
or any repo whose xnu.yml accepts a `machine_config` dispatch input.

    export GITHUB_TOKEN=ghp_xxx
    python3 ci/trigger_build.py --repo JaneAwA/ios-sweet --config POLARIS

Add --wait to follow the run through ci/watch_run.py afterwards.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def api(method, path, token, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path,
        data=body,
        method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "ios16-on-mix2s/ci-trigger",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:600]))


def head_sha(repo, token, ref):
    d = api("GET", "/repos/%s/commits/%s" % (repo, ref), token)
    return d["sha"]


def latest_run(repo, token, branch):
    runs = api("GET", "/repos/%s/actions/runs?per_page=1&branch=%s" % (repo, branch), token)
    if not runs["workflow_runs"]:
        return None
    return runs["workflow_runs"][0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="JaneAwA/ios-sweet")
    ap.add_argument("--workflow", default="xnu.yml")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--config", default="POLARIS", choices=["POLARIS", "SWEET"])
    ap.add_argument("--wait", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("TOKEN")
    if not token:
        sys.exit("set GITHUB_TOKEN (needs actions:write)")

    before = latest_run(args.repo, token, args.ref)
    sha = head_sha(args.repo, token, args.ref)
    print("HEAD %s = %s" % (args.ref, sha))

    api("POST", "/repos/%s/actions/workflows/%s/dispatches" % (args.repo, args.workflow),
        token, {"ref": args.ref, "inputs": {"machine_config": args.config}})

    run = None
    for _ in range(20):
        time.sleep(3)
        now = latest_run(args.repo, token, args.ref)
        if now and (before is None or now["id"] != before["id"]):
            run = now
            break
    if not run:
        sys.exit("dispatched but the new run never showed up - check the Actions tab")
    print("run %s: https://github.com/%s/actions/runs/%s"
          % (run["id"], args.repo, run["id"]))

    if args.wait:
        rc = subprocess.call(
            [sys.executable, os.path.join(os.path.dirname(__file__), "watch_run.py"),
             "--repo", args.repo, "--run", str(run["id"])])
        sys.exit(rc)


if __name__ == "__main__":
    main()
