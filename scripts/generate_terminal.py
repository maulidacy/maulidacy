import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

USERNAME = os.getenv("GITHUB_USERNAME", "maulidacy")
TOKEN = os.environ["GITHUB_TOKEN"]

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "github-profile-terminal",
    "Accept": "application/vnd.github+json",
}


def graphql(query, variables):
    payload = json.dumps({
        "query": query,
        "variables": variables
    }).encode()

    req = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            **HEADERS,
            "Content-Type": "application/json"
        }
    )

    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read())

    if "errors" in result:
        raise RuntimeError(result["errors"])

    return result["data"]


def rest(url):
    req = urllib.request.Request(url, headers=HEADERS)

    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def get_account_created_at():
    query = """
    query($login: String!) {
      user(login: $login) {
        createdAt
      }
    }
    """

    data = graphql(query, {"login": USERNAME})
    return datetime.fromisoformat(
        data["user"]["createdAt"].replace("Z", "+00:00")
    )


def get_contributions():
    created_at = get_account_created_at()
    now = datetime.now(timezone.utc)

    all_days = {}

    start = created_at

    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """

    while start < now:
        end = min(start + timedelta(days=364), now)

        data = graphql(
            query,
            {
                "login": USERNAME,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )

        weeks = data["user"]["contributionsCollection"][
            "contributionCalendar"
        ]["weeks"]

        for week in weeks:
            for day in week["contributionDays"]:
                all_days[day["date"]] = day["contributionCount"]

        start = end + timedelta(days=1)

    return all_days


def calculate_streaks(days):
    ordered = sorted(days.items())

    longest = 0
    current_run = 0

    for _, count in ordered:
        if count > 0:
            current_run += 1
            longest = max(longest, current_run)
        else:
            current_run = 0

    today = datetime.now(timezone.utc).date()
    current = 0

    pointer = today

    # Kalau hari ini belum commit, streak kemarin tetap dihitung.
    if days.get(pointer.isoformat(), 0) == 0:
        pointer -= timedelta(days=1)

    while days.get(pointer.isoformat(), 0) > 0:
        current += 1
        pointer -= timedelta(days=1)

    return current, longest


def get_languages():
    repos = rest(
        f"{REST_URL}/users/{USERNAME}/repos"
        "?per_page=100&type=owner&sort=updated"
    )

    totals = defaultdict(int)

    for repo in repos:
        if repo.get("fork"):
            continue

        languages = rest(repo["languages_url"])

        for language, size in languages.items():
            totals[language] += size

    total_size = sum(totals.values())

    if not total_size:
        return []

    top = sorted(
        totals.items(),
        key=lambda x: x[1],
        reverse=True
    )[:4]

    return [
        (name, round(size / total_size * 100, 1))
        for name, size in top
    ]


def monthly_activity(days):
    now = datetime.now(timezone.utc)

    months = []

    year = now.year
    month = now.month

    for _ in range(12):
        months.append((year, month))

        month -= 1

        if month == 0:
            month = 12
            year -= 1

    months.reverse()

    totals = []

    for y, m in months:
        total = sum(
            count
            for date_str, count in days.items()
            if (
                datetime.fromisoformat(date_str).year == y
                and datetime.fromisoformat(date_str).month == m
            )
        )

        totals.append(total)

    return totals


def chart_points(values):
    x_start = 45
    x_end = 650

    y_top = 170
    y_bottom = 315

    max_value = max(values) if values else 1

    if max_value == 0:
        max_value = 1

    points = []

    for index, value in enumerate(values):
        x = x_start + (
            index * (x_end - x_start) / max(len(values) - 1, 1)
        )

        y = y_bottom - (
            value / max_value
        ) * (y_bottom - y_top)

        points.append(f"{x:.1f},{y:.1f}")

    return " ".join(points)


def language_svg(languages):
    rows = []

    y = 315

    colors = [
        "#58a6ff",
        "#3fb950",
        "#a371f7",
        "#f0883e",
    ]

    for index, (name, percentage) in enumerate(languages):
        width = min(260, percentage / 50 * 260)

        rows.append(f"""
  <text x="755" y="{y}"
        fill="#c9d1d9"
        font-family="monospace"
        font-size="12">
    {name}
  </text>

  <text x="1118" y="{y}"
        text-anchor="end"
        fill="#8b949e"
        font-family="monospace"
        font-size="11">
    {percentage:.1f}%
  </text>

  <rect x="865" y="{y - 9}"
        width="220"
        height="6"
        rx="3"
        fill="#21262d"/>

  <rect x="865" y="{y - 9}"
        width="{width:.1f}"
        height="6"
        rx="3"
        fill="{colors[index]}"/>
""")

        y += 25

    return "".join(rows)


def generate_svg(total, current_streak, longest_streak, months, languages):
    points = chart_points(months)

    return f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="1200"
     height="430"
     viewBox="0 0 1200 430">

  <rect width="1200" height="430"
        rx="14"
        fill="#0d1117"/>

  <rect x="1" y="1"
        width="1198"
        height="428"
        rx="13"
        fill="none"
        stroke="#30363d"
        stroke-width="2"/>

  <!-- Header -->

  <text x="34" y="48"
        fill="#f0f6fc"
        font-family="Arial, sans-serif"
        font-size="21"
        font-weight="600">
    Development Activity
  </text>

  <circle cx="1072" cy="40"
          r="5"
          fill="#3fb950">
    <animate
      attributeName="opacity"
      values="1;0.25;1"
      dur="2s"
      repeatCount="indefinite"/>
  </circle>

  <text x="1087" y="45"
        fill="#8b949e"
        font-family="monospace"
        font-size="12">
    ACTIVE
  </text>

  <line x1="34" y1="68"
        x2="1166" y2="68"
        stroke="#30363d"/>

  <!-- Contribution -->

  <text x="34" y="105"
        fill="#8b949e"
        font-family="monospace"
        font-size="12"
        letter-spacing="1.5">
    CONTRIBUTION ACTIVITY
  </text>

  <text x="34" y="153"
        fill="#f0f6fc"
        font-family="Arial, sans-serif"
        font-size="35"
        font-weight="700">
    {total:,}
  </text>

  <text x="165" y="153"
        fill="#8b949e"
        font-family="Arial, sans-serif"
        font-size="15">
    total contributions
  </text>

  <!-- Graph -->

  <g stroke="#21262d" stroke-width="1">
    <line x1="34" y1="195" x2="675" y2="195"/>
    <line x1="34" y1="235" x2="675" y2="235"/>
    <line x1="34" y1="275" x2="675" y2="275"/>
    <line x1="34" y1="315" x2="675" y2="315"/>
  </g>

  <polyline
    points="{points}"
    fill="none"
    stroke="#3fb950"
    stroke-width="3"
    stroke-linecap="round"
    stroke-linejoin="round"/>

  <text x="34" y="340"
        fill="#6e7681"
        font-family="monospace"
        font-size="10">
    LAST 12 MONTHS
  </text>

  <!-- Divider -->

  <line x1="710" y1="92"
        x2="710" y2="360"
        stroke="#30363d"/>

  <!-- Current streak -->

  <text x="755" y="105"
        fill="#8b949e"
        font-family="monospace"
        font-size="12"
        letter-spacing="1.5">
    CURRENT STREAK
  </text>

  <circle cx="830" cy="181"
          r="52"
          fill="none"
          stroke="#3fb950"
          stroke-width="2"
          opacity="0.2">
    <animate
      attributeName="r"
      values="50;60;50"
      dur="2.5s"
      repeatCount="indefinite"/>
    <animate
      attributeName="opacity"
      values="0.3;0.03;0.3"
      dur="2.5s"
      repeatCount="indefinite"/>
  </circle>

  <circle cx="830" cy="181"
          r="48"
          fill="#11161d"
          stroke="#3fb950"
          stroke-width="3"/>

  <text x="830" y="190"
        text-anchor="middle"
        fill="#3fb950"
        font-family="Arial, sans-serif"
        font-size="30"
        font-weight="700">
    {current_streak}
  </text>

  <text x="830" y="216"
        text-anchor="middle"
        fill="#8b949e"
        font-family="monospace"
        font-size="11">
    DAYS
  </text>

  <text x="930" y="155"
        fill="#8b949e"
        font-family="monospace"
        font-size="11">
    LONGEST
  </text>

  <text x="930" y="184"
        fill="#f0f6fc"
        font-family="Arial, sans-serif"
        font-size="24"
        font-weight="600">
    {longest_streak} days
  </text>

  <!-- Languages -->

  <line x1="755" y1="250"
        x2="1155" y2="250"
        stroke="#30363d"/>

  <text x="755" y="282"
        fill="#8b949e"
        font-family="monospace"
        font-size="12"
        letter-spacing="1.5">
    MOST USED LANGUAGES
  </text>

  {language_svg(languages)}

  <!-- Footer -->

  <line x1="34" y1="385"
        x2="1166" y2="385"
        stroke="#30363d"/>

  <text x="34" y="414"
        fill="#6e7681"
        font-family="monospace"
        font-size="11">
    MAULIDACY / GITHUB
  </text>

  <text x="1166" y="414"
        text-anchor="end"
        fill="#8b949e"
        font-family="monospace"
        font-size="11">
    KEEP LEARNING · KEEP BUILDING
  </text>

</svg>
"""


def main():
    print("Fetching GitHub contributions...")
    days = get_contributions()

    total = sum(days.values())

    current_streak, longest_streak = calculate_streaks(days)

    print("Fetching language statistics...")
    languages = get_languages()

    months = monthly_activity(days)

    svg = generate_svg(
        total,
        current_streak,
        longest_streak,
        months,
        languages,
    )

    os.makedirs("assets", exist_ok=True)

    with open(
        "assets/github-terminal.svg",
        "w",
        encoding="utf-8"
    ) as file:
        file.write(svg)

    print("github-terminal.svg generated")
    print("Total contributions:", total)
    print("Current streak:", current_streak)
    print("Longest streak:", longest_streak)
    print("Languages:", languages)


if __name__ == "__main__":
    main()
