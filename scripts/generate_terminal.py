import html
import json
import os
import time
import urllib.request
from urllib.error import HTTPError, URLError
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


def request_json(request, attempts=3, timeout=20):
    """Open a GitHub API request with a small retry policy."""

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())

        except HTTPError as error:
            retryable = error.code in {429, 500, 502, 503, 504}

            if not retryable or attempt == attempts:
                raise

        except URLError:
            if attempt == attempts:
                raise

        time.sleep(2 ** (attempt - 1))

    raise RuntimeError("GitHub API request failed after retries.")


def graphql(query, variables):
    payload = json.dumps(
        {
            "query": query,
            "variables": variables,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        GRAPHQL_URL,
        data=payload,
        headers={
            **HEADERS,
            "Content-Type": "application/json",
        },
    )

    result = request_json(request)

    if "errors" in result:
        raise RuntimeError(result["errors"])

    return result["data"]


def rest(url):
    request = urllib.request.Request(
        url,
        headers=HEADERS,
    )

    return request_json(request)


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
# STREAKS
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

    # Current streak uses WIB so the date boundary matches the profile owner.
    today = datetime.now(WIB).date()
    pointer = today

    # If there is no contribution yet today, yesterday can still be the
    # latest day in an active streak.
    if days.get(pointer.isoformat(), 0) == 0:
        pointer -= timedelta(days=1)

    current_end = pointer if days.get(pointer.isoformat(), 0) > 0 else None
    current = 0

    while days.get(pointer.isoformat(), 0) > 0:
        current += 1
        pointer -= timedelta(days=1)

    current_start = pointer + timedelta(days=1) if current > 0 else None

    return (
        current,
        current_start,
        current_end,
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
        return f"{format_date(start)} - {format_date(end)}"

    return (
        f"{format_date(start)}, {start.year} - "
        f"{format_date(end)}, {end.year}"
    )


def format_current_streak_period(start):
    if start is None:
        return "NO ACTIVE STREAK"

    return f"{format_date(start)} - PRESENT"


# ============================================================
# ACTIVITY TREND
# ============================================================


def calculate_activity_trend(days):
    """Compare the latest 30 days with the preceding 30 days."""

    today = datetime.now(WIB).date()

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
        if recent_total > 0:
            return {
                "change": None,
                "symbol": "▲",
                "color": "#3fb950",
                "label": "NEW",
                "recent": recent_total,
                "previous": previous_total,
            }

        return {
            "change": 0.0,
            "symbol": "-",
            "color": "#d29922",
            "label": "STABLE",
            "recent": recent_total,
            "previous": previous_total,
        }

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
        "symbol": "-",
        "color": "#d29922",
        "label": "STABLE",
        "recent": recent_total,
        "previous": previous_total,
    }


def activity_status(days):
    """Return a meaningful profile status based on the latest 7 days."""

    today = datetime.now(WIB).date()
    start = today - timedelta(days=6)

    contributions = sum(
        count
        for date_string, count in days.items()
        if start <= datetime.fromisoformat(date_string).date() <= today
    )

    if contributions > 0:
        return {
            "label": "ACTIVE",
            "color": "#3fb950",
        }

    return {
        "label": "IDLE",
        "color": "#6e7681",
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
        # Ignore forks so the card reflects the owner's own projects.
        if repo.get("fork"):
            continue

        languages = rest(repo["languages_url"])

        for language, size in languages.items():
            totals[language] += size

    total_size = sum(totals.values())

    if total_size == 0:
        return []

    # Top 3 keeps the right side clean and avoids footer collisions.
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
    now = datetime.now(WIB)

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
    date_value = datetime(year, month, 1)
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

    # Extra room for names such as "Jupyter Notebook".
    bar_x = 900
    bar_width = 185

    for index, (name, percentage) in enumerate(languages):
        safe_name = html.escape(name)
        width = (percentage / 100) * bar_width

        rows.append(
            f"""
  <text
    x="755"
    y="{y}"
    fill="#c9d1d9"
    font-family="monospace"
    font-size="11"
  >
    {safe_name}
  </text>

  <rect
    x="{bar_x}"
    y="{y - 9}"
    width="{bar_width}"
    height="6"
    rx="3"
    fill="#21262d"
  />

  <rect
    x="{bar_x}"
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
    current_start,
    current_end,
    longest_streak,
    longest_start,
    longest_end,
    months,
    monthly_values,
    languages,
    trend,
    status,
):
    chart_color = "#58a6ff"
    points = chart_points(monthly_values)
    circles = chart_circles(monthly_values, chart_color)
    area_path = chart_area(monthly_values)

    current_period = format_current_streak_period(current_start)
    longest_period = format_streak_period(
        longest_start,
        longest_end,
    )

    first_label = month_label(*months[0])
    middle_label = month_label(*months[len(months) // 2])
    last_label = month_label(*months[-1])

    if trend["change"] is None:
        trend_text = (
            f"{trend['symbol']} NEW ACTIVITY "
            f"VS PREVIOUS 30 DAYS"
        )
    else:
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


    return f"""<svg
  xmlns="http://www.w3.org/2000/svg"
  width="1200"
  height="430"
  viewBox="0 0 1200 430"
>

  <title>GitHub development activity for {html.escape(USERNAME)}</title>

  <!-- Background -->
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


  <!-- Status -->
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
    fill="{status['color']}"
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
    {status['label']}
  </text>

  <line
    x1="34"
    y1="65"
    x2="1166"
    y2="65"
    stroke="#30363d"
  />


  <!-- Contributions -->
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


  <!-- Chart -->
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
    fill="{chart_color}"
    opacity="0.07"
  />

  <polyline
    points="{points}"
    fill="none"
    stroke="{chart_color}"
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


  <!-- Divider -->
  <line
    x1="710"
    y1="92"
    x2="710"
    y2="365"
    stroke="#30363d"
  />


  <!-- Current streak -->
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
    cy="176"
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
    cy="176"
    r="47"
    fill="#11161d"
    stroke="{streak_color}"
    stroke-width="3"
  />

  <text
    x="830"
    y="185"
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
    y="210"
    text-anchor="middle"
    fill="#8b949e"
    font-family="monospace"
    font-size="10"
    letter-spacing="1"
  >
    DAYS
  </text>

  <text
    x="830"
    y="239"
    text-anchor="middle"
    fill="#6e7681"
    font-family="monospace"
    font-size="9"
  >
    {current_period}
  </text>


  <!-- Longest streak -->
  <text
    x="930"
    y="146"
    fill="#8b949e"
    font-family="monospace"
    font-size="10"
    letter-spacing="1.4"
  >
    LONGEST STREAK
  </text>

  <text
    x="930"
    y="176"
    fill="#f0f6fc"
    font-family="Arial, sans-serif"
    font-size="24"
    font-weight="600"
  >
    {longest_streak} days
  </text>

  <text
    x="930"
    y="202"
    fill="#6e7681"
    font-family="monospace"
    font-size="10"
  >
    {longest_period}
  </text>


  <!-- Languages -->
  <line
    x1="755"
    y1="260"
    x2="1155"
    y2="260"
    stroke="#30363d"
  />

  <text
    x="755"
    y="288"
    fill="#8b949e"
    font-family="monospace"
    font-size="12"
    letter-spacing="1.7"
  >
    MOST USED LANGUAGES
  </text>

  {language_svg(languages)}


  <!-- Footer -->
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
    fill="{status['color']}"
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
    AUTO UPDATED · GITHUB ACTIONS
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
        current_start,
        current_end,
        longest_streak,
        longest_start,
        longest_end,
    ) = calculate_streaks(days)

    trend = calculate_activity_trend(days)
    status = activity_status(days)

    print("Fetching language statistics...")
    languages = get_languages()

    months, monthly_values = monthly_activity(days)

    svg = generate_svg(
        total=total,
        current_streak=current_streak,
        current_start=current_start,
        current_end=current_end,
        longest_streak=longest_streak,
        longest_start=longest_start,
        longest_end=longest_end,
        months=months,
        monthly_values=monthly_values,
        languages=languages,
        trend=trend,
        status=status,
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
    print(
        "Current period:",
        format_current_streak_period(current_start),
    )
    print("Longest streak:", longest_streak)
    print(
        "Longest period:",
        format_streak_period(
            longest_start,
            longest_end,
        ),
    )
    if trend["change"] is None:
        trend_log = f"{trend['symbol']} NEW ACTIVITY"
    else:
        trend_log = f"{trend['symbol']} {trend['change']:.1f}%"

    print("30-day trend:", trend_log)
    print("Status:", status["label"])
    print("Languages:", languages)


if __name__ == "__main__":
    main()
