#!/usr/bin/env python3
"""Poll a GitHub Actions run and, when it ends, summarise what really happened.

    export GITHUB_TOKEN=ghp_xxx
    python3 ci/watch_run.py --repo JaneAwA/ios-sweet --run 39470309899

It prints the compile flags that actually reached clang (-arch / -march /
-DARM64_BOARD_CONFIG_*) - that is how every machine-config defect in this port
was caught - and then the first real diagnostics. Exits 0 on success, 1 on
failure.
"""

import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

DIAG = re.compile(r"(error:|fatal error:|Undefined symbols|clang: error|"
                  r"Assertion failed|Stop\.)")


def get(url, token, accept="application/vnd.github+json"):
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + token,
                 "Accept": accept,
                 "User-Agent": "ios16-on-mix2s/ci-watch"})
    return urllib.request.urlopen(req).read()


def analyse(run, repo, token):
    blob = get("https://api.github.com/repos/%s/actions/runs/%s/logs" % (repo, run),
               token, "application/vnd.github.v3+json")
    z = zipfile.ZipFile(io.BytesIO(blob))
    for name in z.namelist():
        if not name.endswith("Build.txt"):
            continue
        lines = z.read(name).decode("utf-8", "replace").splitlines()

        arch, march, boards = set(), set(), set()
        for line in lines:
            if "-c -g -nostdinc" not in line:
                continue
            arch.update(re.findall(r"-arch (\S+)", line))
            march.update(re.findall(r"-march=(\S+)", line))
            boards.update(re.findall(r"-DARM64_BOARD_CONFIG_\w+", line))
        print("--- %s: flags that reached clang ---" % name)
        print("   -arch  :", sorted(arch) or "n/a")
        print("   -march :", sorted(march) or "n/a")
        print("   board  :", sorted(boards) or "n/a")

        print("--- %s: diagnostics ---" % name)
        seen, shown = set(), 0
        for line in lines:
            s = line.strip()
            if not s or "Toolchains/XcodeDefault" in s or not DIAG.search(s):
                continue
            key = s[:110]
            if key in seen:
                continue
            seen.add(key)
            shown += 1
            print("   ", s[:300])
            if shown >= 40:
                print("    ... (truncated)")
                break
        if not shown:
            print("    <no error lines>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="JaneAwA/ios-sweet")
    ap.add_argument("--run", required=True)
    ap.add_argument("--interval", type=int, default=60, help="seconds between polls")
    ap.add_argument("--timeout", type=int, default=90, help="polls before giving up")
    ap.add_argument("--no-analyse", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("TOKEN")
    if not token:
        sys.exit("set GITHUB_TOKEN")

    url = "https://api.github.com/repos/%s/actions/runs/%s" % (args.repo, args.run)
    for i in range(args.timeout):
        d = json.loads(get(url, token))
        print("poll %d: status=%s conclusion=%s" % (i, d.get("status"), d.get("conclusion")),
              flush=True)
        if d.get("status") == "completed":
            print("=== %s ===" % d.get("conclusion"))
            print("https://github.com/%s/actions/runs/%s" % (args.repo, args.run))
            if not args.no_analyse:
                try:
                    analyse(args.run, args.repo, token)
                except Exception as e:
                    print("ANALYSE_FAILED:", e)
            sys.exit(0 if d.get("conclusion") == "success" else 1)
        time.sleep(args.interval)
    sys.exit("still running after %d polls" % args.timeout)


if __name__ == "__main__":
    main()
