"""Gera assets/generated/status.svg com estatísticas reais do GitHub.

Roda no GitHub Actions (ver .github/workflows/profile.yml) usando o GITHUB_TOKEN
do próprio workflow. Sem dependências externas.

Uso local:
    GITHUB_TOKEN=ghp_xxx GITHUB_USER=ViniciuPSantos python3 scripts/generate_status.py
    python3 scripts/generate_status.py --mock dados.json   # testa o layout sem API
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("GITHUB_USER", "ViniciuPSantos")
OUT = Path(__file__).resolve().parent.parent / "assets" / "generated" / "status.svg"

# Linguagens que distorcem o ranking (markup, scripts de build, templates).
EXCLUDE = {
    "HTML", "CSS", "SCSS", "Dockerfile", "Shell", "PowerShell", "Batchfile",
    "Makefile", "Mako", "Procfile", "Jupyter Notebook",
}
TOP_N = 5

QUERY = """
query($login: String!) {
  user(login: $login) {
    pullRequests { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN não definido")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": USER}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        sys.exit(f"Erro da API: {payload['errors']}")
    return payload["data"]["user"]


def streaks(days: list[dict]) -> tuple[int, int]:
    """Sequência atual e maior sequência de dias com contribuição."""
    counts = {d["date"]: d["contributionCount"] for d in days}
    ordered = sorted(counts)
    best = run = 0
    for d in ordered:
        run = run + 1 if counts[d] > 0 else 0
        best = max(best, run)

    today = datetime.now(timezone.utc).date()
    cursor = today if counts.get(today.isoformat(), 0) > 0 else today - timedelta(days=1)
    current = 0
    while counts.get(cursor.isoformat(), 0) > 0:
        current += 1
        cursor -= timedelta(days=1)
    return current, best


def summarize(user: dict) -> dict:
    repos = user["repositories"]
    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [d for w in calendar["weeks"] for d in w["contributionDays"]]
    current, best = streaks(days)

    sizes: dict[str, int] = {}
    for repo in repos["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name not in EXCLUDE:
                sizes[name] = sizes.get(name, 0) + edge["size"]
    total = sum(sizes.values()) or 1
    langs = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]

    return {
        "contributions": calendar["totalContributions"],
        "commits": user["contributionsCollection"]["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "repos": repos["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos["nodes"]),
        "streak": current,
        "best_streak": best,
        "languages": [(n, s / total * 100) for n, s in langs],
    }


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def render(s: dict) -> str:
    rows = [
        ("CONTRIBUIÇÕES", f"{fmt(s['contributions'])}", "último ano"),
        ("COMMITS", f"{fmt(s['commits'])}", "último ano"),
        ("PULL REQUESTS", fmt(s["prs"]), ""),
        ("REPOSITÓRIOS", fmt(s["repos"]), "públicos"),
        ("ESTRELAS", fmt(s["stars"]), ""),
        ("SEQUÊNCIA", f"{s['streak']} {'dia' if s['streak'] == 1 else 'dias'}",
         f"recorde: {s['best_streak']}"),
    ]
    left = []
    for i, (label, value, note) in enumerate(rows):
        y = 104 + i * 32
        left.append(f'<text x="40" y="{y}" class="mono label">{escape(label)}</text>')
        note_svg = f'<tspan class="note" dx="8">{escape(note)}</tspan>' if note else ""
        left.append(f'<text x="200" y="{y}" class="sans value">{escape(value)}{note_svg}</text>')

    right = ['<text x="470" y="104" class="mono label">LINGUAGENS</text>']
    for i, (name, pct) in enumerate(s["languages"]):
        y = 138 + i * 34
        width = max(4.0, 330 * pct / 100)
        right.append(f'<text x="470" y="{y}" class="sans lang">{escape(name)}</text>')
        right.append(f'<text x="800" y="{y}" text-anchor="end" class="mono pct">{pct:.1f}%</text>')
        right.append(f'<rect x="470" y="{y + 8}" width="330" height="6" rx="3" fill="#13254A"/>')
        right.append(
            f'<rect x="470" y="{y + 8}" width="{width:.1f}" height="6" rx="3" fill="url(#bar)">'
            f'<animate attributeName="width" from="0" to="{width:.1f}" begin="{0.15 * i:g}s" '
            f'dur="1.2s" fill="freeze" calcMode="spline" keySplines=".2 .8 .2 1" keyTimes="0;1"/></rect>'
        )
    if not s["languages"]:
        right.append('<text x="470" y="138" class="sans lang">Sem dados ainda</text>')

    desc = (
        f"{s['contributions']} contribuições e {s['commits']} commits no último ano, "
        f"{s['prs']} pull requests, {s['repos']} repositórios públicos, {s['stars']} estrelas. "
        "Linguagens: " + ", ".join(f"{n} {p:.1f}%" for n, p in s["languages"]) + "."
    )
    updated = date.today().strftime("%d/%m/%Y")

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="840" height="340" viewBox="0 0 840 340" role="img" aria-labelledby="title desc">
  <title id="title">Estatísticas do GitHub</title>
  <desc id="desc">{escape(desc)}</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#050913"/><stop offset="1" stop-color="#0B1633"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#4DA3FF"/><stop offset="1" stop-color="#B07CFF"/>
    </linearGradient>
    <pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">
      <path d="M24 0H0V24" fill="none" stroke="#4DA3FF" stroke-opacity=".06"/>
    </pattern>
    <filter id="glow" x="-10%" y="-20%" width="120%" height="140%">
      <feGaussianBlur stdDeviation="4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <style>
    .mono{{font-family:'JetBrains Mono','Cascadia Code',Consolas,'Courier New',monospace}}
    .sans{{font-family:'Segoe UI',Inter,'Helvetica Neue',Arial,sans-serif}}
    .label{{font-size:12px;letter-spacing:2px;fill:#7FB8FF}}
    .value{{font-size:17px;font-weight:700;fill:#EAF4FF}}
    .note{{font-size:12px;font-weight:400;fill:#7F98BC}}
    .lang{{font-size:14px;fill:#EAF4FF}}
    .pct{{font-size:12px;fill:#9DB7DA}}
    .frame{{animation:pulse 3.2s ease-in-out infinite}}
    @keyframes pulse{{0%,100%{{stroke-opacity:.7}}50%{{stroke-opacity:1}}}}
    @media (prefers-reduced-motion:reduce){{.frame{{animation:none}}}}
  </style>

  <rect x="10" y="10" width="820" height="320" rx="6" fill="url(#bg)"/>
  <rect x="10" y="10" width="820" height="320" rx="6" fill="url(#grid)"/>
  <rect class="frame" x="10" y="10" width="820" height="320" rx="6" fill="none" stroke="#4DA3FF" stroke-width="1.5" filter="url(#glow)"/>
  <g fill="none" stroke="#9CD0FF" stroke-width="3" stroke-linecap="square">
    <path d="M4 30V4H30"/><path d="M810 4H836V30"/><path d="M4 310V336H30"/><path d="M810 336H836V310"/>
  </g>
  <rect x="310" y="26" width="220" height="32" rx="3" fill="#0B1A3A" stroke="#4DA3FF" stroke-opacity=".6"/>
  <text x="420" y="47" text-anchor="middle" class="mono" font-size="14" font-weight="700" letter-spacing="6" fill="#EAF4FF">ESTATÍSTICAS</text>

  {chr(10).join("  " + line for line in left).strip()}
  <line x1="440" y1="84" x2="440" y2="290" stroke="#4DA3FF" stroke-opacity=".3"/>
  {chr(10).join("  " + line for line in right).strip()}

  <text x="420" y="314" text-anchor="middle" class="mono" font-size="11" fill="#5F7AA3">sincronizado em {updated} · GitHub Actions</text>
</svg>
"""


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--mock":
        stats = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        stats["languages"] = [tuple(x) for x in stats["languages"]]
    else:
        stats = summarize(fetch())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(stats), encoding="utf-8")
    print(f"status.svg gerado: {OUT}")


if __name__ == "__main__":
    main()
