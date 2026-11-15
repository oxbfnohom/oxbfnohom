#!/usr/bin/env python3
"""Auto-refresh the GitHub profile README for oxbfnohom/oxbfnohom.

Pulls every PUBLIC repo of the user and rebuilds the three generated blocks:

    <!-- SELECTED:BEGIN --> ... <!-- SELECTED:END -->   (curated flagship rows)
    <!-- REPOS:BEGIN -->    ... <!-- REPOS:END -->      (every other repo)
    <!-- ACTIVITY:BEGIN --> ... <!-- ACTIVITY:END -->   (live account strip)

Star counts inside both repo blocks and every number in the activity strip are
refreshed on every run, so the profile follows the account: push a new public
repo and it shows up on the next run (the workflow runs every 5 minutes).

Stdlib only -- runs on GitHub Actions and locally. Optional auth via the
GH_TOKEN / GITHUB_TOKEN env var (raises the API rate limit, sees nothing extra).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
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

ASSETS = Path(__file__).resolve().parent.parent / "assets"
GQL = "https://api.github.com/graphql"
CONTRIB_QUERY = """
{
  user(login: "oxbfnohom") {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date } }
      }
    }
  }
}
"""

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
    # Public only, always: a private repo must never reach the profile, whatever
    # the API returns or whichever token the workflow runs with.
    public = [r for r in repos if not r.get("fork") and r["name"] not in SKIP]
    leaked = [r["name"] for r in public if r.get("private")]
    if leaked:
        raise SystemExit(f"private repo masuk daftar publik, run dibatalkan: {leaked}")
    return public


def esc(text: str) -> str:
    """Keep a repo description from breaking the markdown table."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


WIB = timezone(timedelta(hours=7))  # the owner's timezone, not UTC


def stamp(value: str) -> str:
    """Render a GitHub ISO timestamp as 'today at 20:58 WIB' / '3 days ago'."""
    if not value:
        return "unknown"
    try:
        when = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return value[:10]
    local = when.astimezone(WIB)
    days = (datetime.now(timezone.utc) - when).days
    if days <= 0:
        return f"today at {local:%H:%M} WIB"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def activity_block(repos: list[dict], token: str | None) -> str:
    """Live account strip: totals plus the most recent public push."""
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    followers = None
    try:
        followers = api(f"/users/{USER}", token).get("followers")
    except Exception:
        pass  # the strip still renders, just without the follower count

    latest = max(repos, key=lambda r: r.get("pushed_at") or "", default=None)
    head = f"**{len(repos)}** public repositories · **{total_stars}** stars"
    if followers is not None:
        head += f" · **{followers}** followers"
    if latest is None:
        return head

    name = latest["name"]
    age = stamp(latest.get("pushed_at"))
    lang = latest.get("language")
    tail = f"Last push: **[{name}]({latest['html_url']})** · {age}"
    if lang:
        tail += f" · `{lang}`"
    return f"{head}\n\n{tail}"


def contribution_calendar(token: str | None) -> dict:
    """Public contribution calendar, read straight from GitHub's GraphQL API.

    No third-party stats service sits in the middle, so the numbers are only as
    old as this run (five minutes) instead of somebody else's cache.
    """
    if token:
        req = urllib.request.Request(
            GQL,
            data=json.dumps({"query": CONTRIB_QUERY}).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "User-Agent": "oxbfnohom-profile-readme",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.load(resp)
    else:
        # Local run without a token: borrow the gh CLI's own session.
        done = subprocess.run(
            ["gh", "api", "graphql", "-f", "query=" + CONTRIB_QUERY],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise RuntimeError("gh api graphql gagal: " + done.stderr.strip()[:200])
        payload = json.loads(done.stdout)
    if "errors" in payload:
        raise RuntimeError("graphql error: " + str(payload["errors"][0].get("message")))
    return payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]


def _day(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _fmt(day) -> str:
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def streak_numbers(cal: dict) -> dict:
    """Total, current and longest streak, counted from the raw calendar."""
    days: dict[str, int] = {}
    for week in cal["weeks"]:
        for day in week["contributionDays"]:
            days[day["date"]] = day["contributionCount"]

    today = datetime.now(timezone.utc).date()
    active = sorted(d for d, c in days.items() if c > 0 and d <= today.isoformat())

    # A live streak may end yesterday rather than today; GitHub counts it too.
    cursor = today
    if days.get(today.isoformat(), 0) == 0:
        cursor -= timedelta(days=1)
    start = cursor
    current = 0
    while days.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    # Walk every calendar day, not just the contributing ones: a gap in the
    # sorted "has contributions" list is not a gap in the streak.
    longest, run, run_start = 0, 0, None
    long_start = long_end = None
    for ds in sorted(days):
        if ds > today.isoformat():
            continue  # the calendar pads its final week with future days
        if days[ds] > 0:
            if run == 0:
                run_start = _day(ds)
            run += 1
            if run > longest:
                longest, long_start, long_end = run, run_start, _day(ds)
        else:
            run = 0

    # cursor now sits on the first quiet day just before the live streak.
    current_start = current_end = None
    if current:
        current_end = start
        current_start = start - timedelta(days=current - 1)

    return {
        "total": cal["totalContributions"],
        "current": current,
        "current_start": current_start,
        "current_end": current_end,
        "longest": longest,
        "longest_start": long_start,
        "longest_end": long_end,
        "since": _day(active[0]) if active else today,
    }


def streak_svg(token: str | None) -> str | None:
    """Render the streak card ourselves -- assets/streak.svg, no cache.

    Returns None (and leaves the previous file alone) when GitHub cannot be
    read, so a bad API minute never blanks the card.
    """
    try:
        n = streak_numbers(contribution_calendar(token))
    except Exception as exc:
        print(f"  streak svg            : gagal ({exc}) -- file lama dipertahankan", file=sys.stderr)
        return None

    if n["current"]:
        cur = f"{_fmt(n['current_start'])} - {_fmt(n['current_end'])}"
    else:
        cur = "-"
    long = f"{_fmt(n['longest_start'])} - {_fmt(n['longest_end'])}" if n["longest"] else "-"
    cols = [
        (n["total"], "TOTAL CONTRIBUTIONS", f"{_fmt(n['since'])} - present"),
        (n["current"], "CURRENT STREAK", cur),
        (n["longest"], "LONGEST STREAK", long),
    ]

    cells = []
    for i, (num, label, span) in enumerate(cols):
        cx = 150 + i * 300
        cells.append(
            f'<text x="{cx}" y="86" text-anchor="middle" font-size="56" font-weight="700" '
            f'fill="#FFFFFF">{num}</text>'
        )
        cells.append(f'<rect x="{cx - 24}" y="100" width="48" height="3" rx="1.5" fill="#2E9BE0"/>')
        cells.append(
            f'<text x="{cx}" y="126" text-anchor="middle" font-size="12.5" letter-spacing="1.6" '
            f'fill="#8B96B0">{label}</text>'
        )
        cells.append(
            f'<text x="{cx}" y="148" text-anchor="middle" font-size="11.5" fill="#5A6684">{span}</text>'
        )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="176" viewBox="0 0 900 176" '
        'font-family="sans-serif">\n'
        '  <rect width="900" height="176" rx="10" fill="#0D1117" stroke="#1B2233"/>\n'
        '  <line x1="300" y1="34" x2="300" y2="142" stroke="#1B2233"/>\n'
        '  <line x1="600" y1="34" x2="600" y2="142" stroke="#1B2233"/>\n  '
        + "\n  ".join(cells)
        + "\n</svg>\n"
    )


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
    activity = activity_block(repos, token)
    svg = streak_svg(token)
    text = README.read_text(encoding="utf-8")
    text = splice(text, "<!-- SELECTED:BEGIN -->", "<!-- SELECTED:END -->", selected)
    text = splice(text, "<!-- REPOS:BEGIN -->", "<!-- REPOS:END -->", others)
    text = splice(text, "<!-- ACTIVITY:BEGIN -->", "<!-- ACTIVITY:END -->", activity)
    README.write_text(text, encoding="utf-8", newline="\n")
    if svg is not None:
        ASSETS.joinpath("streak.svg").write_text(svg, encoding="utf-8", newline="\n")

    print(f"repo publik kebaca : {len(repos)}")
    for name in sorted(CURATED):
        hit = next((r for r in repos if r["name"] == name), None)
        print(f"  curated {name:20s} {'OK ' + str(hit['stargazers_count']) + ' stars' if hit else 'MISSING'}")
    print(f"  baris 'other repositories' : {max(len(repos) - len(CURATED), 0)}")
    print("  activity strip : " + activity.replace("\n\n", " | ").replace("**", ""))
    if svg is not None:
        print("  streak svg     : assets/streak.svg ditulis ulang")
    for n in notes:
        print("  note: " + n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
