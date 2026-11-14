#!/usr/bin/env python3
"""Auto-refresh the GitHub profile README for oxbfnohom/oxbfnohom.

Pulls every PUBLIC repo of the user and rebuilds the two generated blocks:

    <!-- SELECTED:BEGIN --> ... <!-- SELECTED:END -->   (curated flagship rows)
    <!-- REPOS:BEGIN -->    ... <!-- REPOS:END -->      (every other repo)

Star counts inside both blocks are refreshed on every run, so the profile
follows the account: push a new repo and it shows up on the next run.

Stdlib only -- runs on GitHub Actions and locally. Optional auth via the
GH_TOKEN / GITHUB_TOKEN env var (raises the API rate limit, sees nothing extra).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

USER = "oxbfnohom"
SKIP = {USER}  # the profile repo itself is not a project
API = "https://api.github.com"

SIGILS = [
    "assets/sigil-radar.svg",
    "assets/sigil-mask.svg",
    "assets/sigil-key.svg",
    "assets/sigil-chip.svg",
]

# Flagship rows: hand-written blurb + stack, icon fixed. Stars stay automatic.
CURATED = {
    "airdrop-tracker": (
        "assets/sigil-radar.svg",
        "Self-hosted agent that runs a research pipeline: it reads the Telegram groups you "
        "already follow, scores new leads, keeps per-project task lists, and re-checks "
        "finished work on a schedule. SQLite, one file, no external queue.",
        "`Next.js` `TypeScript` `SQLite`",
    ),
    "all-about-crime": (
        "assets/sigil-mask.svg",
        "Telegram bot that automates the boring parts of OSINT work: rotating proxies, "
        "virtual cards, throwaway mail, and OTP handling behind one command surface.",
        "`Python` `Telegram`",
    ),
}

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def api(path: str, token: str | None):
    req = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "oxbfnohom-profile-readme",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.load(resp)


def public_repos(token: str | None) -> list[dict]:
    repos: list[dict] = []
    for page in range(1, 4):
        batch = api(f"/users/{USER}/repos?per_page=100&type=public&sort=pushed&page={page}", token)
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
    return [r for r in repos if not r.get("fork") and r["name"] not in SKIP]


def esc(text: str) -> str:
    """Keep a repo description from breaking the markdown table."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def row(repo: dict, icon: str, blurb: str, stack: str) -> str:
    stars = repo.get("stargazers_count", 0)
    label = f"{stars} star" + ("" if stars == 1 else "s")
    name = (
        f'<img src="{icon}" width="28" align="absmiddle" alt=""> '
        f'**[{repo["name"]}]({repo["html_url"]})**<br><sub>{label}</sub>'
    )
    return f"| {name} | {blurb} | {stack} |"


def render(repos: list[dict]) -> tuple[str, str, list[str]]:
    by_name = {r["name"]: r for r in repos}
    notes: list[str] = []

    selected = ["| Project | What it is | Stack |", "| --- | --- | --- |"]
    for name, (icon, blurb, stack) in CURATED.items():
        repo = by_name.get(name)
        if repo:
            selected.append(row(repo, icon, blurb, stack))
        else:
            notes.append(f"curated repo not public/found, skipped: {name}")

    rest = sorted(
        (r for r in repos if r["name"] not in CURATED),
        key=lambda r: (-r.get("stargazers_count", 0), r["name"].lower()),
    )
    others = ["| Repository | What it is | Stack |", "| --- | --- | --- |"]
    if rest:
        for i, repo in enumerate(rest):
            blurb = esc(repo.get("description")) or "_(no description yet)_"
            stack = f"`{repo['language']}`" if repo.get("language") else "-"
            others.append(row(repo, SIGILS[i % len(SIGILS)], blurb, stack))
    else:
        others.append("| _more soon_ |  |  |")

    return "\n".join(selected), "\n".join(others), notes


def splice(text: str, begin: str, end: str, block: str) -> str:
    start = text.find(begin)
    stop = text.find(end)
    if start == -1 or stop == -1 or stop < start:
        raise SystemExit(f"marker tidak ketemu di README: {begin} / {end}")
    return text[: start + len(begin)] + "\n" + block + "\n" + text[stop:]


def main() -> int:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repos = public_repos(token)
    if not repos:
        print("tidak ada repo publik yang kebaca -- README TIDAK diubah", file=sys.stderr)
        return 1

    selected, others, notes = render(repos)
    text = README.read_text(encoding="utf-8")
    text = splice(text, "<!-- SELECTED:BEGIN -->", "<!-- SELECTED:END -->", selected)
    text = splice(text, "<!-- REPOS:BEGIN -->", "<!-- REPOS:END -->", others)
    README.write_text(text, encoding="utf-8", newline="\n")

    print(f"repo publik kebaca : {len(repos)}")
    for name in sorted(CURATED):
        hit = next((r for r in repos if r["name"] == name), None)
        print(f"  curated {name:20s} {'OK ' + str(hit['stargazers_count']) + ' stars' if hit else 'MISSING'}")
    print(f"  baris 'other repositories' : {max(len(repos) - len(CURATED), 0)}")
    for n in notes:
        print("  note: " + n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
