import html
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


USERNAME = os.getenv("GITHUB_USERNAME", "maulidacy")
TOKEN = os.environ["GITHUB_TOKEN"]

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

WIB = ZoneInfo("Asia/Jakarta")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "github-profile-activity",
    "Accept": "application/vnd.github+json",
}


# ============================================================
# API HELPERS
# ============================================================

def graphql(query, variables):
    payload = json.dumps({
        "query": query,
        "variables": variables,
    }).encode("utf-8")

    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            **HEADERS,
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(request) as response:
        result = json.loads(response.read())

    if "errors" in result:
        raise RuntimeError(result["errors"])

    return result["data"]


def rest(url):
    request = urllib.request.Request(
        url,
        headers=HEADERS,
    )

    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


# ============================================================
# CONTRIBUTION DATA
# ============================================================

def get_account_created_at():
    query = """
    query($login: String!) {
      user(login: $login) {
        createdAt
      }
    }
    """

    data = graphql(
        query,
        {"login": USERNAME},
    )

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
        end = min(
            start + timedelta(days=364),
            now,
        )

        data = graphql(
            query,
            {
                "login": USERNAME,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )

        weeks = (
            data["user"]["contributionsCollection"]
            ["contributionCalendar"]
            ["weeks"]
        )

        for week in weeks:
            for day in week["contributionDays"]:
                all_days[day["date"]] = day["contributionCount"]

        start = end + timedelta(days=1)

    return all_days


# ============================================================
# STREAK
# ============================================================

def calculate_streaks(days):
    ordered = sorted(days.items())

    longest = 0
    longest_start = None
    longest_end = None

    running = 0
    running_start = None

    for date_string, count in ordered:
        date_value = datetime.fromisoformat(date_string).date()

        if count > 0:
            if running == 0:
                running_start = date_value

            running += 1

            if running > longest:
                longest = running
                longest_start = running_start
                longest_end = date_value

        else:
            running = 0
            running_start = None

    # Current streak
    today = datetime.now(timezone.utc).date()
    pointer = today

    # Jika hari ini belum commit, streak kemarin tetap dihitung.
    if days.get(pointer.isoformat(), 0) == 0:
        pointer -= timedelta(days=1)

    current = 0

    while days.get(pointer.isoformat(), 0) > 0:
        current += 1
        pointer -= timedelta(days=1)

    return (
        current,
        longest,
        longest_start,
        longest_end,
    )


def format_date(date_value):
    if date_value is None:
        return "-"

    return f"{date_value.strftime('%b')} {date_value.day}"


def format_streak_period(start, end):
    if start is None or end is None:
        return "-"

    if start.year == end.year:
        return (
            f"{format_date(start)} — "
            f"{format_date(end)}"
        )

    return (
        f"{format_date(start)}, {start.year} — "
        f"{format_date(end)}, {end.year}"
    )


# ============================================================
# ACTIVITY TREND
# ============================================================

def calculate_activity_trend(days):
    """
    Bandingkan 30 hari terakhir dengan 30 hari sebelumnya.

    Naik   -> hijau
    Turun  -> merah
    Stabil -> amber
    """

    today = datetime.now(timezone.utc).date()

    recent_start = today - timedelta(days=29)

    previous_start = today - timedelta(days=59)
    previous_end = today - timedelta(days=30)

    recent_total = 0
    previous_total = 0

    for date_string, count in days.items():
        date_value = datetime.fromisoformat(date_string).date()

        if recent_start <= date_value <= today:
            recent_total += count

        elif previous_start <= date_value <= previous_end:
            previous_total += count

    if previous_total == 0:
        change = 100.0 if recent_total > 0 else 0.0
    else:
        change = (
            (recent_total - previous_total)
            / previous_total
        ) * 100

    if change > 2:
        return {
            "change": change,
            "symbol": "▲",
            "color": "#3fb950",
            "label": "UP",
            "recent": recent_total,
            "previous": previous_total,
        }

    if change < -2:
        return {
            "change": change,
            "symbol": "▼",
            "color": "#f85149",
            "label": "DOWN",
            "recent": recent_total,
            "previous": previous_total,
        }

    return {
        "change": change,
        "symbol": "—",
        "color": "#d29922",
        "label": "STABLE",
        "recent": recent_total,
        "previous": previous_total,
    }


# ============================================================
# LANGUAGE DATA
# ============================================================

def get_repositories():
    repositories = []

    page = 1

    while True:
        batch = rest(
            f"{REST_URL}/users/{USERNAME}/repos"
            f"?per_page=100"
            f"&page={page}"
            f"&type=owner"
            f"&sort=updated"
        )

        if not batch:
            break

        repositories.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    return repositories


def get_languages():
    repositories = get_repositories()

    totals = defaultdict(int)

    for repo in repositories:
        # Fork tidak dihitung agar lebih mewakili project sendiri.
        if repo.get("fork"):
            continue

        languages = rest(repo["languages_url"])

        for language, size in languages.items():
            totals[language] += size

    total_size = sum(totals.values())

    if total_size == 0:
        return []

    # Hanya top 3 supaya layout tetap clean.
    top = sorted(
        totals.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:3]

    return [
        (
            language,
            round(size / total_size * 100, 1),
        )
        for language, size in top
    ]


# ============================================================
# MONTHLY CHART
# ============================================================

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

    for target_year, target_month in months:
        total = 0

        for date_string, count in days.items():
            date_value = datetime.fromisoformat(date_string)

            if (
                date_value.year == target_year
                and date_value.month == target_month
            ):
                total += count

        totals.append(total)

    return months, totals


def chart_coordinates(values):
    x_start = 45
    x_end = 650

    y_top = 170
    y_bottom = 315

    maximum = max(values) if values else 1

    if maximum == 0:
        maximum = 1

    coordinates = []

    count = len(values)

    for index, value in enumerate(values):
        x = x_start + (
            index
            * (x_end - x_start)
            / max(count - 1, 1)
        )

        y = y_bottom - (
            value / maximum
        ) * (y_bottom - y_top)

        coordinates.append((x, y))

    return coordinates


def chart_points(values):
    return " ".join(
        f"{x:.1f},{y:.1f}"
        for x, y in chart_coordinates(values)
    )


def chart_circles(values, color):
    circles = []

    for x, y in chart_coordinates(values):
        circles.append(
            f"""
  <circle
    cx="{x:.1f}"
    cy="{y:.1f}"
    r="4"
    fill="#0d1117"
    stroke="{color}"
    stroke-width="2"
  />"""
        )

    return "".join(circles)


def chart_area(values):
    coordinates = chart_coordinates(values)

    if not coordinates:
        return ""

    first_x = coordinates[0][0]
    last_x = coordinates[-1][0]

    path = [
        f"M{coordinates[0][0]:.1f} {coordinates[0][1]:.1f}"
    ]

    for x, y in coordinates[1:]:
        path.append(f"L{x:.1f} {y:.1f}")

    path.append(f"L{last_x:.1f} 315")
    path.append(f"L{first_x:.1f} 315")
    path.append("Z")

    return " ".join(path)


def month_label(year, month):
    date_value = datetime(
        year,
        month,
        1,
    )

    return date_value.strftime("%b %Y").upper()


# ============================================================
# LANGUAGE SVG
# ============================================================

def language_svg(languages):
    rows = []

    y = 312

    colors = [
        "#58a6ff",
        "#3fb950",
        "#a371f7",
    ]

    bar_width = 250

    for index, (name, percentage) in enumerate(languages):
        safe_name = html.escape(name)

        # 100% = full bar.
        width = (
            percentage / 100
        ) * bar_width

        rows.append(
            f"""
  <text
    x="755"
    y="{y}"
    fill="#c9d1d9"
    font-family="monospace"
    font-size="12"
  >
    {safe_name}
  </text>

  <rect
    x="855"
    y="{y - 9}"
    width="{bar_width}"
    height="6"
    rx="3"
    fill="#21262d"
  />

  <rect
    x="855"
    y="{y - 9}"
    width="{width:.1f}"
    height="6"
    rx="3"
    fill="{colors[index]}"
  />

  <text
    x="1145"
    y="{y}"
    text-anchor="end"
    fill="#8b949e"
    font-family="monospace"
    font-size="11"
  >
    {percentage:.1f}%
  </text>
"""
        )

        y += 27

    return "".join(rows)


# ============================================================
# SVG GENERATOR
# ============================================================

def generate_svg(
    total,
    current_streak,
    longest_streak,
    longest_start,
    longest_end,
    months,
    monthly_values,
    languages,
    trend,
):
    points = chart_points(monthly_values)

    circles = chart_circles(
        monthly_values,
        trend["color"],
    )

    area_path = chart_area(monthly_values)

    longest_period = format_streak_period(
        longest_start,
        longest_end,
    )

    first_label = month_label(*months[0])
    middle_label = month_label(*months[len(months) // 2])
    last_label = month_label(*months[-1])

    change = abs(trend["change"])

    trend_text = (
        f"{trend['symbol']} "
        f"{change:.1f}% "
        f"VS PREVIOUS 30 DAYS"
    )

    streak_color = (
        "#3fb950"
        if current_streak > 0
        else "#6e7681"
    )

    if current_streak > 0:
        streak_animation = """
    <animate
      attributeName="r"
      values="50;61;50"
      dur="2.5s"
      repeatCount="indefinite"
    />

    <animate
      attributeName="opacity"
      values="0.30;0.03;0.30"
      dur="2.5s"
      repeatCount="indefinite"
    />"""
    else:
        streak_animation = ""

    synced = datetime.now(WIB).strftime(
        "%d %b %Y · %H:%M WIB"
    ).upper()

    return f"""<svg
  xmlns="http://www.w3.org/2000/svg"
  width="1200"
  height="430"
  viewBox="0 0 1200 430"
>

  <!-- =================================================== -->
  <!-- BACKGROUND -->
  <!-- =================================================== -->

  <rect
    width="1200"
    height="430"
    rx="14"
    fill="#0d1117"
  />

  <rect
    x="1"
    y="1"
    width="1198"
    height="428"
    rx="13"
    fill="none"
    stroke="#30363d"
    stroke-width="2"
  />


  <!-- =================================================== -->
  <!-- STATUS -->
  <!-- =================================================== -->

  <text
    x="34"
    y="42"
    fill="#8b949e"
    font-family="monospace"
    font-size="11"
    letter-spacing="1.5"
  >
    MAULIDACY / DEVELOPMENT SNAPSHOT
  </text>

  <circle
    cx="1094"
    cy="37"
    r="5"
    fill="#3fb950"
  >
    <animate
      attributeName="opacity"
      values="1;0.25;1"
      dur="2s"
      repeatCount="indefinite"
    />
  </circle>

  <text
    x="1108"
    y="42"
    fill="#8b949e"
    font-family="monospace"
    font-size="11"
  >
    ACTIVE
  </text>

  <line
    x1="34"
    y1="65"
    x2="1166"
    y2="65"
    stroke="#30363d"
  />


  <!-- =================================================== -->
  <!-- CONTRIBUTIONS -->
  <!-- =================================================== -->

  <text
    x="34"
    y="101"
    fill="#8b949e"
    font-family="monospace"
    font-size="12"
    letter-spacing="1.7"
  >
    CONTRIBUTIONS
  </text>

  <text
    x="34"
    y="151"
    fill="#f0f6fc"
    font-family="Arial, sans-serif"
    font-size="36"
    font-weight="700"
  >
    {total:,}
  </text>

  <text
    x="165"
    y="151"
    fill="#8b949e"
    font-family="Arial, sans-serif"
    font-size="15"
  >
    total contributions
  </text>

  <text
    x="34"
    y="176"
    fill="{trend['color']}"
    font-family="monospace"
    font-size="11"
  >
    {trend_text}
  </text>


  <!-- =================================================== -->
  <!-- CHART -->
  <!-- =================================================== -->

  <g
    stroke="#21262d"
    stroke-width="1"
  >
    <line x1="34" y1="205" x2="675" y2="205"/>
    <line x1="34" y1="243" x2="675" y2="243"/>
    <line x1="34" y1="281" x2="675" y2="281"/>
    <line x1="34" y1="319" x2="675" y2="319"/>
  </g>

  <path
    d="{area_path}"
    fill="{trend['color']}"
    opacity="0.07"
  />

  <polyline
    points="{points}"
    fill="none"
    stroke="{trend['color']}"
    stroke-width="3"
    stroke-linecap="round"
    stroke-linejoin="round"
  />

  {circles}

  <text
    x="34"
    y="344"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    {first_label}
  </text>

  <text
    x="350"
    y="344"
    text-anchor="middle"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    {middle_label}
  </text>

  <text
    x="650"
    y="344"
    text-anchor="end"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    {last_label}
  </text>


  <!-- =================================================== -->
  <!-- DIVIDER -->
  <!-- =================================================== -->

  <line
    x1="710"
    y1="92"
    x2="710"
    y2="365"
    stroke="#30363d"
  />


  <!-- =================================================== -->
  <!-- CURRENT STREAK -->
  <!-- =================================================== -->

  <text
    x="755"
    y="101"
    fill="#8b949e"
    font-family="monospace"
    font-size="12"
    letter-spacing="1.7"
  >
    CURRENT STREAK
  </text>

  <circle
    cx="830"
    cy="181"
    r="51"
    fill="none"
    stroke="{streak_color}"
    stroke-width="2"
    opacity="0.25"
  >
    {streak_animation}
  </circle>

  <circle
    cx="830"
    cy="181"
    r="47"
    fill="#11161d"
    stroke="{streak_color}"
    stroke-width="3"
  />

  <text
    x="830"
    y="190"
    text-anchor="middle"
    fill="{streak_color}"
    font-family="Arial, sans-serif"
    font-size="31"
    font-weight="700"
  >
    {current_streak}
  </text>

  <text
    x="830"
    y="216"
    text-anchor="middle"
    fill="#8b949e"
    font-family="monospace"
    font-size="10"
    letter-spacing="1"
  >
    DAYS
  </text>


  <!-- =================================================== -->
  <!-- LONGEST STREAK -->
  <!-- =================================================== -->

  <text
    x="930"
    y="151"
    fill="#8b949e"
    font-family="monospace"
    font-size="10"
    letter-spacing="1.4"
  >
    LONGEST STREAK
  </text>

  <text
    x="930"
    y="181"
    fill="#f0f6fc"
    font-family="Arial, sans-serif"
    font-size="24"
    font-weight="600"
  >
    {longest_streak} days
  </text>

  <text
    x="930"
    y="207"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    {longest_period}
  </text>


  <!-- =================================================== -->
  <!-- LANGUAGES -->
  <!-- =================================================== -->

  <line
    x1="755"
    y1="250"
    x2="1155"
    y2="250"
    stroke="#30363d"
  />

  <text
    x="755"
    y="280"
    fill="#8b949e"
    font-family="monospace"
    font-size="12"
    letter-spacing="1.7"
  >
    MOST USED LANGUAGES
  </text>

  {language_svg(languages)}


  <!-- =================================================== -->
  <!-- FOOTER -->
  <!-- =================================================== -->

  <line
    x1="34"
    y1="388"
    x2="1166"
    y2="388"
    stroke="#30363d"
  />

  <circle
    cx="40"
    cy="410"
    r="3"
    fill="#3fb950"
  />

  <text
    x="52"
    y="414"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    GITHUB DATA
  </text>

  <text
    x="1166"
    y="414"
    text-anchor="end"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    LAST SYNC · {synced}
  </text>

</svg>
"""


# ============================================================
# MAIN
# ============================================================

def main():
    print("Fetching GitHub contributions...")

    days = get_contributions()

    total = sum(days.values())

    (
        current_streak,
        longest_streak,
        longest_start,
        longest_end,
    ) = calculate_streaks(days)

    trend = calculate_activity_trend(days)

    print("Fetching language statistics...")

    languages = get_languages()

    months, monthly_values = monthly_activity(days)

    svg = generate_svg(
        total=total,
        current_streak=current_streak,
        longest_streak=longest_streak,
        longest_start=longest_start,
        longest_end=longest_end,
        months=months,
        monthly_values=monthly_values,
        languages=languages,
        trend=trend,
    )

    os.makedirs(
        "assets",
        exist_ok=True,
    )

    output_path = "assets/github-terminal.svg"

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(svg)

    print()
    print("GitHub activity SVG generated successfully.")
    print("-------------------------------------------")
    print("Output:", output_path)
    print("Total contributions:", total)
    print("Current streak:", current_streak)
    print("Longest streak:", longest_streak)
    print(
        "Longest period:",
        format_streak_period(
            longest_start,
            longest_end,
        ),
    )
    print(
        "30-day trend:",
        f"{trend['symbol']} {trend['change']:.1f}%",
    )
    print("Languages:", languages)


if __name__ == "__main__":
    main()
