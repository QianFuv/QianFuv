"""Generate the animated profile assets and refresh README marker blocks.

The script reads public profile data from the GitHub GraphQL API and writes:

* ``assets/neofetch-{dark,light}.svg``: terminal-style header with live stats.
* ``assets/repo-<name>-{dark,light}.svg``: cards for recently active projects.
* README blocks between ``PROJECTS`` and ``TECH`` markers.

Environment variables:
    GITHUB_TOKEN: Token used for the GraphQL API.
    GITHUB_LOGIN: Profile owner login. Defaults to ``QianFuv``.
"""

from __future__ import annotations

import base64
import datetime as dt
import html
import json
import os
import pathlib
import re
import unicodedata
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
API_URL = "https://api.github.com/graphql"
FONT = "'JetBrains Mono','Cascadia Code','SFMono-Regular',Consolas,Menlo,monospace"
FEATURED_COUNT = 4
ACTIVITY_WEEKS = 12
MIN_ICON_SHARE = 0.0005

EXTRA_SKILL_ICONS = ("git", "githubactions")

SKILL_ICONS = {
    "Astro": "astro",
    "C": "c",
    "C#": "cs",
    "C++": "cpp",
    "CSS": "css",
    "Dart": "dart",
    "Dockerfile": "docker",
    "Elixir": "elixir",
    "Go": "go",
    "HTML": "html",
    "Haskell": "haskell",
    "Java": "java",
    "JavaScript": "js",
    "Julia": "julia",
    "Kotlin": "kotlin",
    "Less": "less",
    "Lua": "lua",
    "MATLAB": "matlab",
    "Nim": "nim",
    "Nix": "nix",
    "OCaml": "ocaml",
    "PHP": "php",
    "Perl": "perl",
    "PowerShell": "powershell",
    "Python": "py",
    "R": "r",
    "Ruby": "ruby",
    "Rust": "rust",
    "SCSS": "sass",
    "Sass": "sass",
    "Scala": "scala",
    "Shell": "bash",
    "Solidity": "solidity",
    "Svelte": "svelte",
    "Swift": "swift",
    "TeX": "latex",
    "TypeScript": "ts",
    "Vue": "vue",
    "Zig": "zig",
}

TOPIC_ICONS = {
    "angular",
    "ansible",
    "arduino",
    "astro",
    "aws",
    "azure",
    "blender",
    "bun",
    "cloudflare",
    "cmake",
    "deno",
    "django",
    "docker",
    "dotnet",
    "electron",
    "express",
    "fastapi",
    "flask",
    "flutter",
    "gcp",
    "godot",
    "gradle",
    "graphql",
    "kubernetes",
    "linux",
    "mongodb",
    "mysql",
    "nestjs",
    "nextjs",
    "nginx",
    "nodejs",
    "nuxtjs",
    "postgres",
    "prisma",
    "pytorch",
    "react",
    "redis",
    "sqlite",
    "tailwind",
    "tauri",
    "tensorflow",
    "threejs",
    "unity",
    "unreal",
    "vite",
    "vue",
    "wasm",
}

THEMES = {
    "dark": {
        "bg": "#0d1117",
        "bar": "#161b22",
        "border": "#30363d",
        "text": "#e6edf3",
        "muted": "#7d8590",
        "accent": "#539bf5",
        "accent2": "#a371f7",
        "green": "#3fb950",
        "track": "#21262d",
    },
    "light": {
        "bg": "#ffffff",
        "bar": "#f6f8fa",
        "border": "#d0d7de",
        "text": "#1f2328",
        "muted": "#656d76",
        "accent": "#0969da",
        "accent2": "#8250df",
        "green": "#1a7f37",
        "track": "#eaeef2",
    },
}

ICON_COLORS = {"git": "#f05032", "githubactions": "#2088ff"}

PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    login name bio websiteUrl createdAt avatarUrl(size: 160)
    followers { totalCount }
    repositories(first: 100, privacy: PUBLIC, isFork: false, ownerAffiliations: OWNER,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description url stargazerCount forkCount pushedAt isArchived
        primaryLanguage { name color }
        repositoryTopics(first: 20) { nodes { topic { name } } }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date } }
      }
    }
  }
}
"""


REPO_ICON = (
    "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7"
    ".75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5"
    "a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"
)


def graphql(query: str, variables: dict) -> dict:
    """Run a GitHub GraphQL query.

    Args:
        query: GraphQL document.
        variables: Query variables.

    Returns:
        The ``data`` object of the response.

    Raises:
        RuntimeError: If the API reports errors.
    """
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['GITHUB_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_data_uri(url: str) -> str:
    """Download an image and encode it as a data URI.

    Args:
        url: Image URL.

    Returns:
        A base64 data URI usable inside an SVG image element.
    """
    with urllib.request.urlopen(url, timeout=30) as response:
        content_type = response.headers.get_content_type()
        body = response.read()
    return f"data:{content_type};base64,{base64.b64encode(body).decode()}"


def escape(text: str) -> str:
    """Escape text for SVG and HTML output.

    Args:
        text: Raw text.

    Returns:
        Escaped text.
    """
    return html.escape(text, quote=True)


def text_width(text: str, font_size: float) -> float:
    """Estimate the rendered width of monospace text.

    Args:
        text: Text to measure.
        font_size: Font size in pixels.

    Returns:
        Approximate width in pixels, counting wide CJK characters as one em.
    """
    return sum(font_size if unicodedata.east_asian_width(char) in "WF" else font_size * 0.6 for char in text)


def wrap_text(text: str, max_width: float, font_size: float, max_lines: int) -> list[str]:
    """Wrap text to a pixel width, truncating with an ellipsis.

    Args:
        text: Text to wrap.
        max_width: Maximum line width in pixels.
        font_size: Font size in pixels.
        max_lines: Maximum number of lines.

    Returns:
        Wrapped lines.
    """
    lines: list[str] = []
    current = ""
    for token in re.findall(r"[A-Za-z0-9_\-./:+#&']+\s*|\s+|.", text):
        if current and text_width(current + token, font_size) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip()
        else:
            current += token
    if current.strip():
        lines.append(current.rstrip())
    if len(lines) <= max_lines:
        return lines
    last = lines[max_lines - 1]
    while last and text_width(last + "…", font_size) > max_width:
        last = last[:-1]
    return lines[: max_lines - 1] + [last.rstrip() + "…"]


def relative_time(timestamp: str, now: dt.datetime) -> str:
    """Format a timestamp as a short relative age.

    Args:
        timestamp: ISO 8601 timestamp.
        now: Reference time.

    Returns:
        Text such as ``3h ago`` or ``2d ago``.
    """
    seconds = (now - dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("y", 31_536_000), ("mo", 2_592_000), ("d", 86_400), ("h", 3_600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit} ago"
    return "just now"


def account_age(created_at: str, now: dt.datetime) -> str:
    """Format account age as years, months, and days.

    Args:
        created_at: Account creation timestamp.
        now: Reference time.

    Returns:
        Text such as ``4 years, 1 month, 22 days``.
    """
    start = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    today = now.date()
    months = (today.year - start.year) * 12 + today.month - start.month
    if today.day < start.day:
        months -= 1
    anchor_year, anchor_month = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
    anchor = start.replace(year=anchor_year, month=anchor_month, day=min(start.day, 28))
    days = (today - anchor).days
    parts = [(months // 12, "year"), (months % 12, "month"), (days, "day")]
    return ", ".join(f"{value} {unit}{'s' if value != 1 else ''}" for value, unit in parts if value)


def streaks(days: list[dict]) -> tuple[int, int]:
    """Compute current and longest daily contribution streaks.

    Args:
        days: Contribution calendar days in chronological order.

    Returns:
        A tuple of current streak and longest streak in days.
    """
    counts = [day["contributionCount"] for day in days]
    longest = run = 0
    for count in counts:
        run = run + 1 if count else 0
        longest = max(longest, run)
    current = 0
    for index, count in enumerate(reversed(counts)):
        if count:
            current += 1
        elif index:
            break
    return current, longest


def language_totals(repositories: list[dict]) -> list[tuple[str, str, int]]:
    """Sum language bytes across repositories.

    Args:
        repositories: Repository nodes.

    Returns:
        ``(name, color, bytes)`` tuples sorted by size.
    """
    totals: dict[str, list] = {}
    for repository in repositories:
        for edge in repository["languages"]["edges"]:
            entry = totals.setdefault(edge["node"]["name"], [edge["node"]["color"] or "#8b949e", 0])
            entry[1] += edge["size"]
    return sorted(((name, color, size) for name, (color, size) in totals.items()), key=lambda item: -item[2])


def render_neofetch(profile: dict, stats: dict, theme: dict) -> str:
    """Render the terminal-style header card.

    Args:
        profile: User profile data.
        stats: Derived statistics.
        theme: Color theme.

    Returns:
        SVG markup.
    """
    width, left_x, value_x = 860, 300, 392
    prompt = f"{profile['login'].lower()}@github:~$ neofetch"
    prompt_width = text_width(prompt, 14)
    title = f"{profile['name'] or profile['login']}@{profile['login']}"
    rows = [
        ("Bio", profile["bio"] or "-"),
        ("Uptime", stats["uptime"]),
        ("Host", (profile["websiteUrl"] or f"github.com/{profile['login']}").removeprefix("https://").rstrip("/")),
        ("Repos", f"{stats['repos']} public · {stats['stars']} stars · {profile['followers']['totalCount']} followers"),
        ("Commits", f"{stats['commits']:,} in the past year · {stats['contributions']:,} contributions"),
        ("Streak", f"{stats['streak']} days current · {stats['longest']} days best"),
        ("Focus", f"{stats['focus']} · pushed {stats['focus_age']}"),
    ]
    parts: list[str] = []
    line_index = 0

    def line(content: str) -> None:
        nonlocal line_index
        delay = 1.4 + line_index * 0.12
        parts.append(f'<g class="fade" style="animation-delay:{delay:.2f}s">{content}</g>')
        line_index += 1

    line(f'<text x="{left_x}" y="110" class="title">{escape(title)}</text>')
    line(
        f'<line x1="{left_x}" y1="122" x2="{left_x + text_width(title, 16):.0f}" y2="122" stroke="{theme["muted"]}" stroke-dasharray="6 3"/>'
    )
    y = 152
    for key, value in rows:
        line(f'<text x="{left_x}" y="{y}" class="key">{key}</text><text x="{value_x}" y="{y}" class="value">{escape(value)}</text>')
        y += 24

    bar_width = width - value_x - 30
    total = sum(size for _, _, size in stats["languages"]) or 1
    segments, offset = [], 0.0
    for name, color, size in stats["languages"]:
        segment = bar_width * size / total
        segments.append(f'<rect x="{value_x + offset:.1f}" y="{y - 10}" width="{segment:.1f}" height="10" fill="{color}"/>')
        offset += segment
    line(
        (
            f'<text x="{left_x}" y="{y}" class="key">Langs</text>'
            f'<clipPath id="lang-clip"><rect x="{value_x}" y="{y - 10}" width="0" height="10" rx="5">'
            f'<animate attributeName="width" from="0" to="{bar_width}" begin="2.4s" dur="1.2s" fill="freeze" calcMode="spline" keySplines=".2 .8 .2 1" keyTimes="0;1"/></rect></clipPath>'
            f'<rect x="{value_x}" y="{y - 10}" width="{bar_width}" height="10" rx="5" fill="{theme["track"]}"/>'
            f'<g clip-path="url(#lang-clip)">{"".join(segments)}</g>'
        )
    )
    y += 22
    legend_x = value_x
    legend_items = []
    for name, color, size in stats["languages"][:6]:
        label = f"{name} {size / total * 100:.1f}%"
        item_width = 16 + text_width(label, 11) + 18
        if legend_x + item_width > width - 20:
            line("".join(legend_items))
            legend_items, legend_x, y = [], value_x, y + 18
        legend_items.append(
            f'<circle cx="{legend_x + 4}" cy="{y - 4}" r="4" fill="{color}"/>'
            f'<text x="{legend_x + 14}" y="{y}" class="small">{escape(label)}</text>'
        )
        legend_x += item_width
    line("".join(legend_items))
    y += 26
    line(
        "".join(
            f'<rect x="{left_x + index * 26}" y="{y - 12}" width="22" height="14" rx="2" fill="{color}"/>'
            for index, color in enumerate(stats["stack_colors"])
        )
    )
    height = y + 26

    weeks = stats["weeks"][-52:]
    peak = max(weeks) or 1
    ring_radius, ring_gap, spark_height, label_height = 92, 24, 46, 22
    left_group_height = ring_radius * 2 + ring_gap + spark_height + label_height
    avatar_center = 36 + (height - 36 - left_group_height) / 2 + ring_radius
    spark_left, spark_base, bar_step = 30, avatar_center + ring_radius + ring_gap + spark_height, 4.2
    spark = "".join(
        f'<rect class="grow" style="animation-delay:{1.2 + index * 0.02:.2f}s" x="{spark_left + index * bar_step:.1f}" '
        f'y="{spark_base - max(2, 46 * count / peak):.1f}" width="3" height="{max(2, 46 * count / peak):.1f}" rx="1" '
        f'fill="{theme["accent"]}" fill-opacity="{0.35 + 0.65 * count / peak:.2f}"/>'
        for index, count in enumerate(weeks)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}">
<style>
.title{{fill:{theme["accent"]};font-size:16px;font-weight:700}}
.key{{fill:{theme["accent"]};font-size:14px;font-weight:700}}
.value{{fill:{theme["text"]};font-size:14px}}
.muted{{fill:{theme["muted"]};font-size:14px}}
.small{{fill:{theme["muted"]};font-size:11px}}
.prompt{{font-size:14px}}
.fade{{opacity:0;animation:fade .5s ease-out forwards}}
.grow{{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .6s ease-out forwards}}
.cursor{{animation:blink 1s step-end infinite}}
@keyframes fade{{from{{opacity:0;transform:translateX(-6px)}}to{{opacity:1;transform:none}}}}
@keyframes grow{{to{{transform:scaleY(1)}}}}
@keyframes blink{{50%{{opacity:0}}}}
@media (prefers-reduced-motion:reduce){{.fade,.grow{{animation:none;opacity:1;transform:none}}}}
</style>
<defs>
<clipPath id="avatar"><circle cx="140" cy="{avatar_center}" r="70"/></clipPath>
<clipPath id="typing"><rect x="{left_x}" y="62" width="0" height="22"><animate attributeName="width" from="0" to="{prompt_width + 4:.0f}" begin="0.2s" dur="1s" fill="freeze" calcMode="discrete" values="{";".join(f"{prompt_width * step / len(prompt):.0f}" for step in range(len(prompt) + 1))}"/></rect></clipPath>
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{theme["accent"]}"/><stop offset="1" stop-color="{theme["accent2"]}"/></linearGradient>
</defs>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12" fill="{theme["bg"]}" stroke="{theme["border"]}"/>
<path d="M0.5 12.5a12 12 0 0 1 12-12h{width - 25}a12 12 0 0 1 12 12v24h-{width - 1}z" fill="{theme["bar"]}"/>
<line x1="0.5" y1="36.5" x2="{width - 0.5}" y2="36.5" stroke="{theme["border"]}"/>
<circle cx="22" cy="18.5" r="6" fill="#ff5f56"/><circle cx="42" cy="18.5" r="6" fill="#ffbd2e"/><circle cx="62" cy="18.5" r="6" fill="#27c93f"/>
<text x="{width / 2}" y="23" text-anchor="middle" class="small">{escape(profile["login"].lower())}@github: ~</text>
<g clip-path="url(#typing)"><text x="{left_x}" y="78" class="prompt"><tspan fill="{theme["green"]}">{escape(profile["login"].lower())}@github</tspan><tspan fill="{theme["text"]}">:</tspan><tspan fill="{theme["accent"]}">~</tspan><tspan fill="{theme["text"]}">$ neofetch</tspan></text></g>
<rect class="cursor" x="{left_x}" y="65" width="8" height="16" fill="{theme["text"]}"><animate attributeName="x" from="{left_x}" to="{left_x + prompt_width + 4:.0f}" begin="0.2s" dur="1s" fill="freeze" calcMode="discrete" values="{";".join(f"{left_x + prompt_width * step / len(prompt) + 2:.0f}" for step in range(len(prompt) + 1))}"/></rect>
<circle cx="140" cy="{avatar_center}" r="84" fill="none" stroke="url(#ring)" stroke-width="2.5" stroke-dasharray="40 14" stroke-linecap="round"><animateTransform attributeName="transform" type="rotate" from="0 140 {avatar_center}" to="360 140 {avatar_center}" dur="14s" repeatCount="indefinite"/></circle>
<circle cx="140" cy="{avatar_center}" r="92" fill="none" stroke="{theme["accent2"]}" stroke-opacity=".35" stroke-width="1" stroke-dasharray="3 9"><animateTransform attributeName="transform" type="rotate" from="360 140 {avatar_center}" to="0 140 {avatar_center}" dur="30s" repeatCount="indefinite"/></circle>
<image href="{stats["avatar"]}" x="70" y="{avatar_center - 70}" width="140" height="140" clip-path="url(#avatar)"/>
{spark}
<text x="{spark_left}" y="{spark_base + 18}" class="small">contributions · last 52 weeks</text>
<line x1="{left_x - 26}" y1="56" x2="{left_x - 26}" y2="{height - 20}" stroke="{theme["border"]}" stroke-dasharray="2 4"/>
{"".join(parts)}
</svg>
"""


def render_repo_card(repository: dict, activity: list[int], commit_count: int, now: dt.datetime, theme: dict) -> str:
    """Render one repository card.

    Args:
        repository: Repository node.
        activity: Weekly commit counts, oldest first.
        commit_count: Commits on the default branch in the activity window.
        now: Reference time.
        theme: Color theme.

    Returns:
        SVG markup.
    """
    width, height = 420, 146
    description = wrap_text(repository["description"] or "No description yet.", width - 40, 12, 2)
    language = repository["primaryLanguage"] or {"name": "Text", "color": theme["muted"]}
    peak = max(activity) or 1
    spark_right, spark_base = width - 20, 114
    bars = "".join(
        f'<rect class="grow" style="animation-delay:{0.3 + index * 0.05:.2f}s" x="{spark_right - (len(activity) - index) * 9 + 3}" '
        f'y="{spark_base - max(2, 22 * count / peak):.1f}" width="6" height="{max(2, 22 * count / peak):.1f}" rx="1.5" '
        f'fill="{theme["green"]}" fill-opacity="{0.35 + 0.65 * count / peak:.2f}"/>'
        for index, count in enumerate(activity)
    )
    description_lines = "".join(
        f'<text x="20" y="{64 + index * 18}" class="desc">{escape(text)}</text>' for index, text in enumerate(description)
    )
    meta_x = 20
    meta = [
        f'<circle cx="{meta_x + 5}" cy="126" r="5" fill="{language["color"] or theme["muted"]}"/>',
        f'<text x="{meta_x + 16}" y="130" class="meta">{escape(language["name"])}</text>',
    ]
    meta_x += 16 + text_width(language["name"], 12) + 18
    for icon, value in (("★", repository["stargazerCount"]), ("⑂", repository["forkCount"])):
        meta.append(f'<text x="{meta_x}" y="130" class="meta">{icon} {value}</text>')
        meta_x += text_width(f"{icon} {value}", 12) + 18
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}">
<style>
.name{{fill:{theme["accent"]};font-size:15px;font-weight:700}}
.desc{{fill:{theme["text"]};font-size:12px}}
.meta{{fill:{theme["muted"]};font-size:12px}}
.small{{fill:{theme["muted"]};font-size:10px}}
.grow{{transform-box:fill-box;transform-origin:bottom;transform:scaleY(0);animation:grow .5s ease-out forwards}}
@keyframes grow{{to{{transform:scaleY(1)}}}}
@media (prefers-reduced-motion:reduce){{.grow{{animation:none;transform:none}}}}
</style>
<defs><linearGradient id="shine" x1="0" x2="1"><stop offset="0" stop-color="{theme["accent"]}" stop-opacity="0"/><stop offset=".5" stop-color="{theme["accent"]}"/><stop offset="1" stop-color="{theme["accent2"]}" stop-opacity="0"/>
<animateTransform attributeName="gradientTransform" type="translate" values="-1 0;1 0" dur="4s" repeatCount="indefinite"/></linearGradient>
<clipPath id="card"><rect width="{width}" height="{height}" rx="10"/></clipPath></defs>
<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="{theme["bg"]}" stroke="{theme["border"]}"/>
<rect width="{width}" height="2" fill="url(#shine)" clip-path="url(#card)"/>
<path transform="translate(20 21)" fill="{theme["muted"]}" d="{REPO_ICON}"/>
<text x="44" y="34" class="name">{escape(repository["name"])}</text>
<text x="{width - 20}" y="33" text-anchor="end" class="small">updated {relative_time(repository["pushedAt"], now)}</text>
{description_lines}
{"".join(meta)}
<text x="{spark_right}" y="130" text-anchor="end" class="small">{commit_count} commit{"" if commit_count == 1 else "s"} · {ACTIVITY_WEEKS}w</text>
{bars}
</svg>
"""


def weekly_activity(owner: str, name: str, now: dt.datetime) -> tuple[list[int], int]:
    """Count default-branch commits per week for a repository.

    Args:
        owner: Repository owner.
        name: Repository name.
        now: Reference time.

    Returns:
        Weekly counts oldest first, and the total commit count in the window.
    """
    windows = []
    for index in range(ACTIVITY_WEEKS):
        until = now - dt.timedelta(weeks=ACTIVITY_WEEKS - 1 - index)
        since = until - dt.timedelta(weeks=1)
        windows.append(f'w{index}: history(since: "{since.isoformat()}", until: "{until.isoformat()}") {{ totalCount }}')
    query = (
        "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) {"
        " defaultBranchRef { target { ... on Commit { " + " ".join(windows) + " } } } } }"
    )
    branch = graphql(query, {"owner": owner, "name": name})["repository"]["defaultBranchRef"]
    if not branch:
        return [0] * ACTIVITY_WEEKS, 0
    counts = [branch["target"][f"w{index}"]["totalCount"] for index in range(ACTIVITY_WEEKS)]
    return counts, sum(counts)


def replace_block(text: str, marker: str, content: str) -> str:
    """Replace the content between README markers.

    Args:
        text: README text.
        marker: Marker name such as ``PROJECTS``.
        content: Replacement content.

    Returns:
        Updated README text.
    """
    pattern = re.compile(rf"(<!-- {marker}:START -->)(.*?)(<!-- {marker}:END -->)", re.S)
    return pattern.sub(lambda match: f"{match.group(1)}\n{content}\n{match.group(3)}", text)


def picture(path_stem: str, alt: str, width: str) -> str:
    """Build a theme-aware picture element for generated assets.

    Args:
        path_stem: Asset path without the ``-dark.svg`` or ``-light.svg`` suffix.
        alt: Alternative text.
        width: Image width attribute.

    Returns:
        HTML markup.
    """
    return (
        f'<picture><source media="(prefers-color-scheme: dark)" srcset="{path_stem}-dark.svg">'
        f'<img alt="{escape(alt)}" src="{path_stem}-light.svg" width="{width}"></picture>'
    )


def main() -> None:
    """Fetch profile data, render assets, and update README blocks."""
    login = os.environ.get("GITHUB_LOGIN", "QianFuv")
    now = dt.datetime.now(dt.timezone.utc)
    profile = graphql(PROFILE_QUERY, {"login": login})["user"]
    repositories = [repo for repo in profile["repositories"]["nodes"] if repo["name"].lower() != login.lower()]
    active = [repo for repo in repositories if not repo["isArchived"]]
    calendar = profile["contributionsCollection"]["contributionCalendar"]
    days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    current_streak, longest_streak = streaks(days)
    languages = language_totals(active)
    featured = [repo for repo in active if repo["description"]][:FEATURED_COUNT]
    focus = featured[0] if featured else repositories[0]

    icon_colors: dict[str, str] = {}
    language_bytes = sum(size for _, _, size in languages) or 1
    for name, color, size in languages:
        if size / language_bytes >= MIN_ICON_SHARE and name in SKILL_ICONS:
            icon_colors.setdefault(SKILL_ICONS[name], color)
    for repository in active:
        for node in repository["repositoryTopics"]["nodes"]:
            if node["topic"]["name"] in TOPIC_ICONS:
                icon_colors.setdefault(node["topic"]["name"], "#8b949e")
    for icon in EXTRA_SKILL_ICONS:
        icon_colors.setdefault(icon, "#8b949e")
    icons = list(icon_colors)

    stats = {
        "uptime": account_age(profile["createdAt"], now),
        "repos": profile["repositories"]["totalCount"],
        "stars": sum(repo["stargazerCount"] for repo in repositories),
        "commits": profile["contributionsCollection"]["totalCommitContributions"],
        "contributions": calendar["totalContributions"],
        "streak": current_streak,
        "longest": longest_streak,
        "focus": focus["name"],
        "focus_age": relative_time(focus["pushedAt"], now),
        "languages": languages,
        "weeks": [sum(day["contributionCount"] for day in week["contributionDays"]) for week in calendar["weeks"]],
        "avatar": fetch_data_uri(profile["avatarUrl"]),
        "stack_colors": [ICON_COLORS.get(icon, color) for icon, color in icon_colors.items()],
    }

    ASSETS.mkdir(exist_ok=True)
    for stale in ASSETS.glob("repo-*.svg"):
        stale.unlink()
    for mode, theme in THEMES.items():
        (ASSETS / f"neofetch-{mode}.svg").write_text(render_neofetch(profile, stats, theme), encoding="utf-8")

    cells = []
    for repository in featured:
        activity, commit_count = weekly_activity(login, repository["name"], now)
        slug = re.sub(r"[^A-Za-z0-9_.-]", "-", repository["name"])
        for mode, theme in THEMES.items():
            (ASSETS / f"repo-{slug}-{mode}.svg").write_text(
                render_repo_card(repository, activity, commit_count, now, theme), encoding="utf-8"
            )
        cells.append(f'<a href="{repository["url"]}">{picture(f"assets/repo-{slug}", repository["name"], "49%")}</a>')

    readme = README.read_text(encoding="utf-8")
    readme = replace_block(readme, "PROJECTS", '<p align="center">\n' + "\n".join(cells) + "\n</p>")
    readme = replace_block(
        readme,
        "TECH",
        f'<p align="center"><img alt="Tech stack" src="https://skillicons.dev/icons?i={",".join(icons)}&perline=12"></p>',
    )
    readme = replace_block(readme, "UPDATED", f'<p align="right"><sub>auto-updated {now:%Y-%m-%d %H:%M} UTC</sub></p>')
    README.write_text(readme, encoding="utf-8")


if __name__ == "__main__":
    main()
