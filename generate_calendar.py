import os
import json
import urllib.request
from datetime import date, timedelta

# -----------------------------
# CONFIG
# -----------------------------

DATA_SOURCE_ID = "9e99f171-b5f2-4206-9547-a1d6e3fe8526"

PLATFORMS = ["RED", "INS", "DY", "PYQ"]

STATUS_MAP = {
    "Not started": "NS",
    "In progress": "IP",
    "Done": "DN",
}

NOTION_VERSION = "2026-03-11"


# -----------------------------
# NOTION API
# -----------------------------

def query_notion():
    token = os.environ.get("NOTION_TOKEN")

    if not token:
        raise RuntimeError("NOTION_TOKEN is missing")

    all_pages = []
    start_cursor = None

    while True:
        body = {
            "page_size": 100
        }

        if start_cursor:
            body["start_cursor"] = start_cursor

        request = urllib.request.Request(
            f"https://api.notion.com/v1/data_sources/{DATA_SOURCE_ID}/query",
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request) as response:
            data = json.loads(response.read().decode("utf-8"))

        all_pages.extend(data.get("results", []))

        if not data.get("has_more"):
            break

        start_cursor = data.get("next_cursor")

    return all_pages


# -----------------------------
# PROPERTY HELPERS
# -----------------------------

def get_title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(
                item.get("plain_text", "")
                for item in prop.get("title", [])
            ).strip()

    return "Untitled"


def get_post_date(page):
    prop = page.get("properties", {}).get("Post Date")

    if not prop or prop.get("type") != "date":
        return None

    return prop.get("date")


def get_platforms(page):
    prop = page.get("properties", {}).get("Platform")

    if not prop:
        return []

    prop_type = prop.get("type")

    if prop_type == "select":
        selected = prop.get("select")
        return [selected["name"]] if selected else []

    if prop_type == "multi_select":
        return [
            item["name"]
            for item in prop.get("multi_select", [])
        ]

    return []


def get_status(page):
    prop = page.get("properties", {}).get("Status")

    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "status":
        status = prop.get("status")
        return status["name"] if status else ""

    if prop_type == "select":
        selected = prop.get("select")
        return selected["name"] if selected else ""

    return ""


def get_category(page):
    prop = page.get("properties", {}).get("Category")

    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "select":
        selected = prop.get("select")
        return selected["name"] if selected else ""

    if prop_type == "multi_select":
        return ", ".join(
            item["name"]
            for item in prop.get("multi_select", [])
        )

    return ""


# -----------------------------
# ICS HELPERS
# -----------------------------

def escape_ics(value):
    value = str(value)

    return (
        value
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def ics_date(date_string):
    return date_string[:10].replace("-", "")


def add_one_day(date_string):
    d = date.fromisoformat(date_string[:10])
    return (d + timedelta(days=1)).strftime("%Y%m%d")


def make_event(page, platform):
    title = get_title(page)
    post_date = get_post_date(page)

    raw_status = get_status(page)
    short_status = STATUS_MAP.get(raw_status, raw_status)

    category = get_category(page)

    start = post_date["start"]

    # Notion may have an end date for date ranges.
    visible_end = post_date.get("end") or start

    # All-day ICS end dates are exclusive.
    end_exclusive = add_one_day(visible_end)

    summary_parts = [platform]

    if short_status:
        summary_parts.append(short_status)

    summary_parts.append(title)

    summary = " · ".join(summary_parts)

    description = []

    if category:
        description.append(f"Category: {category}")

    if page.get("url"):
        description.append(f"Notion: {page['url']}")

    description_text = "\n".join(description)

    uid = (
        page["id"].replace("-", "")
        + "-"
        + platform.lower()
        + "@chloe-content-calendar"
    )

    lines = [
        "BEGIN:VEVENT",
        f"UID:{escape_ics(uid)}",
        f"DTSTART;VALUE=DATE:{ics_date(start)}",
        f"DTEND;VALUE=DATE:{end_exclusive}",
        f"SUMMARY:{escape_ics(summary)}",
    ]

    if description_text:
        lines.append(
            f"DESCRIPTION:{escape_ics(description_text)}"
        )

    if page.get("url"):
        lines.append(
            f"URL:{page['url']}"
        )

    lines.extend([
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ])

    return "\r\n".join(lines)


# -----------------------------
# GENERATE CALENDARS
# -----------------------------

def generate_calendar(pages, platform):
    events = []

    for page in pages:
        post_date = get_post_date(page)

        if not post_date or not post_date.get("start"):
            continue

        platforms = [
            p.upper()
            for p in get_platforms(page)
        ]

        if platform not in platforms:
            continue

        events.append(
            make_event(page, platform)
        )

    calendar_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chloe//Notion Content Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{platform} Content",
    ]

    calendar_lines.extend(events)

    calendar_lines.append("END:VCALENDAR")
    calendar_lines.append("")

    return "\r\n".join(calendar_lines)


def main():
    print("Reading Notion database...")

    pages = query_notion()

    print(f"Found {len(pages)} Notion pages.")

    os.makedirs("output", exist_ok=True)

    for platform in PLATFORMS:
        calendar = generate_calendar(
            pages,
            platform
        )

        filename = (
            f"output/{platform.lower()}.ics"
        )

        with open(
            filename,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:
            file.write(calendar)

        print(
            f"Created {filename}"
        )

    print("Done!")


if __name__ == "__main__":
    main()
