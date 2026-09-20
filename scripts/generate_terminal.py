import html
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

USERNAME = os.getenv("GITHUB_USERNAME", "maulidacy")
TOKEN = os.environ["GITHUB_TOKEN"]

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

WIB = ZoneInfo("Asia/Jakarta")

REQUEST_TIMEOUT = 20
MAX_RETRIES = 3

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "github-profile-activity",
    "Accept": "application/vnd.github+json",
}


# ============================================================
# HTTP / API
# ============================================================

def request_json(request):
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                return json.loads(response.read())

        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
        ) as exc:
            last_error = exc

            if attempt == MAX_RETRIES - 1:
                break

            time.sleep(2 ** attempt)

    raise RuntimeError(
        f"GitHub API request failed after {MAX_RETRIES} attempts: {last_error}"
    )


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
# CONTRIBUTIONS
# ============================================================

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
            ["contributionCalendar"]["weeks"]
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

    today = datetime.now(WIB).date()
    pointer = today

    # Jika hari ini belum ada contribution, streak kemarin masih boleh aktif.
    if days.get(pointer.isoformat(), 0) == 0:
        pointer -= timedelta(days=1)

    current_end = (
        pointer
        if days.get(pointer.isoformat(), 0) > 0
        else None
    )

    current = 0

    while days.get(pointer.isoformat(), 0) > 0:
        current += 1
        pointer -= timedelta(days=1)

    current_start = (
        pointer + timedelta(days=1)
        if current > 0
        else None
    )

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


def format_period(start, end):
    if start is None or end is None:
        return "-"

    if start.year == end.year:
        return f"{format_date(start)} - {format_date(end)}"

    return (
        f"{format_date(start)}, {start.year} - "
        f"{format_date(end)}, {end.year}"
    )


def format_current_period(start):
    if start is None:
        return "NO ACTIVE STREAK"

    return f"{format_date(start)} - PRESENT"


# ============================================================
# TREND
# ============================================================

def calculate_activity_trend(days):
    """
    Bandingkan 30 hari terakhir dengan 30 hari sebelumnya.

    UP     -> hijau
    DOWN   -> merah
    STABLE -> amber
    NEW    -> biru
    """

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
                "symbol": "●",
                "color": "#58a6ff",
                "label": "NEW ACTIVITY",
            }

        return {
            "change": 0.0,
            "symbol": "-",
            "color": "#d29922",
            "label": "STABLE",
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
        }

    if change < -2:
        return {
            "change": change,
            "symbol": "▼",
            "color": "#f85149",
            "label": "DOWN",
        }

    return {
        "change": change,
        "symbol": "-",
        "color": "#d29922",
        "label": "STABLE",
    }


def activity_status(days):
    today = datetime.now(WIB).date()
    start = today - timedelta(days=6)

    recent = sum(
        count
        for date_string, count in days.items()
        if start <= datetime.fromisoformat(date_string).date() <= today
    )

    if recent > 0:
        return {
            "label": "ACTIVE",
            "color": "#3fb950",
        }

    return {
        "label": "IDLE",
        "color": "#8b949e",
    }


# ============================================================
# LANGUAGES
# ============================================================

def get_repositories():
    repositories = []
    page = 1

    while True:
        batch = rest(
            f"{REST_URL}/users/{USERNAME}/repos"
            f"?per_page=100&page={page}&type=owner&sort=updated"
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
        if repo.get("fork"):
            continue

        languages = rest(repo["languages_url"])

        for language, size in languages.items():
            totals[language] += size

    total_size = sum(totals.values())

    if total_size == 0:
        return []

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
    x_start = 42
    x_end = 678
    y_top = 145
    y_bottom = 285

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
        f"M{coordinates[0][0]:.1f} "
        f"{coordinates[0][1]:.1f}"
    ]

    for x, y in coordinates[1:]:
        path.append(f"L{x:.1f} {y:.1f}")

    path.append(f"L{last_x:.1f} 285")
    path.append(f"L{first_x:.1f} 285")
    path.append("Z")

    return " ".join(path)


def month_label(year, month):
    return datetime(
        year,
        month,
        1,
    ).strftime("%b %Y").upper()


# ============================================================
# LANGUAGE SVG
# ============================================================

def language_svg(languages):
    rows = []

    y = 401
    bar_x = 486
    bar_width = 150

    colors = [
        "#58a6ff",
        "#3fb950",
        "#a371f7",
    ]

    for index, (name, percentage) in enumerate(languages):
        safe_name = html.escape(name)
        width = (percentage / 100) * bar_width

        rows.append(
            f"""
  <text
    x="374"
    y="{y}"
    fill="#c9d1d9"
    font-family="monospace"
    font-size="12"
  >
    {safe_name}
  </text>

  <rect
    x="{bar_x}"
    y="{y - 9}"
    width="{bar_width}"
    height="7"
    rx="3.5"
    fill="#21262d"
  />

  <rect
    x="{bar_x}"
    y="{y - 9}"
    width="{width:.1f}"
    height="7"
    rx="3.5"
    fill="{colors[index]}"
  />

  <text
    x="676"
    y="{y}"
    text-anchor="end"
    fill="#8b949e"
    font-family="monospace"
    font-size="10.5"
  >
    {percentage:.1f}%
  </text>
"""
        )

        y += 36

    return "".join(rows)


# ============================================================
# SVG GENERATOR
# ============================================================

def generate_svg(
    total,
    current_streak,
    current_start,
    longest_streak,
    longest_start,
    longest_end,
    months,
    monthly_values,
    languages,
    trend,
    status,
):
    chart_color = trend["color"]

    points = chart_points(monthly_values)
    circles = chart_circles(
        monthly_values,
        chart_color,
    )
    area_path = chart_area(monthly_values)

    longest_period = format_period(
        longest_start,
        longest_end,
    )

    first_label = month_label(*months[0])
    middle_label = month_label(
        *months[len(months) // 2]
    )
    last_label = month_label(*months[-1])

    if trend["change"] is None:
        trend_text = "● NEW ACTIVITY"
    else:
        trend_text = (
            f"{trend['symbol']} "
            f"{abs(trend['change']):.1f}% "
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
      values="43;49;43"
      dur="2.5s"
      repeatCount="indefinite"
    />
    <animate
      attributeName="opacity"
      values="0.28;0.04;0.28"
      dur="2.5s"
      repeatCount="indefinite"
    />"""
    else:
        streak_animation = ""

    return f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="720"
     height="520"
     viewBox="0 0 720 520">

  <!-- Background -->
  <rect width="720" height="520" rx="14" fill="#0d1117"/>

  <rect x="1" y="1"
        width="718" height="518"
        rx="13"
        fill="none"
        stroke="#30363d"
        stroke-width="2"/>

  <!-- Header status -->
  <circle cx="640" cy="30"
          r="4.5"
          fill="{status['color']}">
    <animate
      attributeName="opacity"
      values="1;0.3;1"
      dur="2s"
      repeatCount="indefinite"/>
  </circle>

  <text x="653" y="34"
        fill="#8b949e"
        font-family="monospace"
        font-size="11">
    {status['label']}
  </text>

  <line x1="28" y1="50"
        x2="692" y2="50"
        stroke="#30363d"/>

  <!-- ================================================= -->
  <!-- ROW 1 : CONTRIBUTIONS -->
  <!-- ================================================= -->

  <text x="34" y="78"
        fill="#8b949e"
        font-family="monospace"
        font-size="11"
        letter-spacing="1.5">
    CONTRIBUTIONS
  </text>

  <text x="34" y="114"
        fill="#f0f6fc"
        font-family="Arial, sans-serif"
        font-size="31"
        font-weight="700">
    {total:,}
  </text>

  <text x="140" y="114"
        fill="#8b949e"
        font-family="Arial, sans-serif"
        font-size="14">
    total contributions
  </text>

  <text x="686" y="109"
        text-anchor="end"
        fill="{trend['color']}"
        font-family="monospace"
        font-size="10.5">
    {trend_text}
  </text>

  <!-- Chart grid -->
  <g stroke="#21262d" stroke-width="1">
    <line x1="34" y1="155" x2="686" y2="155"/>
    <line x1="34" y1="198" x2="686" y2="198"/>
    <line x1="34" y1="241" x2="686" y2="241"/>
    <line x1="34" y1="285" x2="686" y2="285"/>
  </g>

  <path d="{area_path}"
        fill="{chart_color}"
        opacity="0.07"/>

  <polyline points="{points}"
        fill="none"
        stroke="{chart_color}"
        stroke-width="3"
        stroke-linecap="round"
        stroke-linejoin="round"/>

  {circles}

  <text x="34" y="304"
        fill="#6e7681"
        font-family="monospace"
        font-size="9.5">
    {first_label}
  </text>

  <text x="360" y="304"
        text-anchor="middle"
        fill="#6e7681"
        font-family="monospace"
        font-size="9.5">
    {middle_label}
  </text>

  <text x="686" y="304"
        text-anchor="end"
        fill="#6e7681"
        font-family="monospace"
        font-size="9.5">
    {last_label}
  </text>

  <line x1="28" y1="324"
        x2="692" y2="324"
        stroke="#30363d"/>

  <!-- ================================================= -->
  <!-- ROW 2 LEFT : CURRENT & LONGEST STREAK -->
  <!-- ================================================= -->

  <text x="34" y="351"
        fill="#8b949e"
        font-family="monospace"
        font-size="11"
        letter-spacing="1.4">
    CURRENT STREAK
  </text>

  <!-- Animated outer ring -->
  <circle cx="92" cy="420"
          r="44"
          fill="none"
          stroke="{streak_color}"
          stroke-width="2"
          opacity="0.22">
    {streak_animation}
  </circle>

  <!-- Main streak ring -->
  <circle cx="92" cy="420"
          r="39"
          fill="#11161d"
          stroke="{streak_color}"
          stroke-width="3"/>

  <text x="92" y="429"
        text-anchor="middle"
        fill="{streak_color}"
        font-family="Arial, sans-serif"
        font-size="27"
        font-weight="700">
    {current_streak}
  </text>

  <text x="92" y="449"
        text-anchor="middle"
        fill="#8b949e"
        font-family="monospace"
        font-size="8.5"
        letter-spacing="0.7">
    DAYS
  </text>

  <!-- Longest streak -->
  <text x="190" y="385"
        fill="#8b949e"
        font-family="monospace"
        font-size="10"
        letter-spacing="1.1">
    LONGEST STREAK
  </text>

  <text x="190" y="416"
        fill="#f0f6fc"
        font-family="Arial, sans-serif"
        font-size="24"
        font-weight="700">
    {longest_streak} days
  </text>

  <text x="190" y="444"
        fill="#6e7681"
        font-family="monospace"
        font-size="9.5">
    {longest_period}
  </text>

  <!-- Vertical divider -->
  <line x1="340" y1="348"
        x2="340" y2="492"
        stroke="#30363d"/>

  <!-- ================================================= -->
  <!-- ROW 2 RIGHT : LANGUAGES -->
  <!-- ================================================= -->

  <text x="374" y="351"
        fill="#8b949e"
        font-family="monospace"
        font-size="11"
        letter-spacing="1.4">
    MOST USED LANGUAGES
  </text>

  {language_svg(languages)}

  <!-- Footer -->
  <line x1="28" y1="500"
        x2="692" y2="500"
        stroke="#30363d"/>


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
        _current_end,
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
        longest_streak=longest_streak,
        longest_start=longest_start,
        longest_end=longest_end,
        months=months,
        monthly_values=monthly_values,
        languages=languages,
        trend=trend,
        status=status,
    )

    os.makedirs("assets", exist_ok=True)

    output_path = "assets/github-terminal.svg"

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.write(svg)

    print()
    print("Generated:", output_path)
    print("Total contributions:", total)
    print("Current streak:", current_streak)
    print("Longest streak:", longest_streak)
    print("Trend:", trend["label"], trend["change"])
    print("Languages:", languages)


if __name__ == "__main__":
    main()
