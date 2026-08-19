import os
import json
import urllib.request
from datetime import date, timedelta, datetime, timezone


# =========================================================
# CONFIG
# =========================================================

DATA_SOURCE_ID = "9e99f171-b5f2-4206-9547-a1d6e3fe8526"

NOTION_VERSION = "2026-03-11"

PLATFORMS = [
    "RED",
    "INS",
    "DY",
    "PYQ",
]

STATUS_MAP = {
    "not started": "NS",
    "in progress": "IP",
    "done": "DN",
}


# =========================================================
# NOTION API
# =========================================================

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
            data = json.loads(
                response.read().decode("utf-8")
            )

        all_pages.extend(
            data.get("results", [])
        )

        if not data.get("has_more"):
            break

        start_cursor = data.get("next_cursor")

    return all_pages


# =========================================================
# NOTION PROPERTY HELPERS
# =========================================================

def get_title(page):
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            title = "".join(
                item.get("plain_text", "")
                for item in prop.get("title", [])
            ).strip()

            return title or "Untitled"

    return "Untitled"


def get_post_date(page):
    prop = (
        page
        .get("properties", {})
        .get("Post Date")
    )

    if not prop:
        return None

    if prop.get("type") != "date":
        return None

    return prop.get("date")


def get_platforms(page):
    prop = (
        page
        .get("properties", {})
        .get("Platform")
    )

    if not prop:
        return []

    prop_type = prop.get("type")

    if prop_type == "select":
        selected = prop.get("select")

        if not selected:
            return []

        return [
            selected.get("name", "").strip()
        ]

    if prop_type == "multi_select":
        return [
            item.get("name", "").strip()
            for item in prop.get(
                "multi_select",
                []
            )
            if item.get("name")
        ]

    return []


def get_status(page):
    prop = (
        page
        .get("properties", {})
        .get("Status")
    )

    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "status":
        status = prop.get("status")

        if not status:
            return ""

        return status.get("name", "").strip()

    if prop_type == "select":
        selected = prop.get("select")

        if not selected:
            return ""

        return selected.get("name", "").strip()

    return ""


def get_category(page):
    prop = (
        page
        .get("properties", {})
        .get("Category")
    )

    if not prop:
        return ""

    prop_type = prop.get("type")

    if prop_type == "select":
        selected = prop.get("select")

        if not selected:
            return ""

        return selected.get("name", "").strip()

    if prop_type == "multi_select":
        return ", ".join(
            item.get("name", "").strip()
            for item in prop.get(
                "multi_select",
                []
            )
            if item.get("name")
        )

    return ""


# =========================================================
# ICS HELPERS
# =========================================================

def escape_ics_text(value):
    value = str(value)

    value = (
        value
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

    return (
        value
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def to_ics_date(value):
    return (
        value[:10]
        .replace("-", "")
    )


def add_one_day(value):
    d = date.fromisoformat(
        value[:10]
    )

    next_day = (
        d + timedelta(days=1)
    )

    return next_day.strftime(
        "%Y%m%d"
    )


def to_ics_timestamp(value=None):
    if value:
        dt = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00"
            )
        )
    else:
        dt = datetime.now(
            timezone.utc
        )

    dt = dt.astimezone(
        timezone.utc
    )

    return dt.strftime(
        "%Y%m%dT%H%M%SZ"
    )


def fold_ics_line(line, limit=75):
    """
    RFC 5545 line folding.
    Keeps each physical content line within ~75 UTF-8 octets.
    Continuation lines begin with one space.
    """

    if len(
        line.encode("utf-8")
    ) <= limit:
        return line

    lines = []
    current = ""

    for char in line:
        candidate = current + char

        if len(
            candidate.encode("utf-8")
        ) > limit:
            lines.append(current)

            # continuation line starts with a space
            current = " " + char
        else:
            current = candidate

    if current:
        lines.append(current)

    return "\r\n".join(lines)


# =========================================================
# CREATE ONE EVENT
# =========================================================

def make_event(page, platform):
    title = get_title(page)

    post_date = get_post_date(page)

    if not post_date:
        return None

    start = post_date.get("start")

    if not start:
        return None

    visible_end = (
        post_date.get("end")
        or start
    )

    # All-day DTEND is exclusive.
    end_exclusive = add_one_day(
        visible_end
    )

    raw_status = get_status(page)

    short_status = STATUS_MAP.get(
        raw_status.lower(),
        raw_status
    )

    category = get_category(page)

    summary_parts = [
        platform
    ]

    if short_status:
        summary_parts.append(
            short_status
        )

    summary_parts.append(
        title
    )

    summary = " · ".join(
        summary_parts
    )

    description_parts = []

    if category:
        description_parts.append(
            f"Category: {category}"
        )

    notion_url = page.get(
        "url",
        ""
    )

    if notion_url:
        description_parts.append(
            f"Notion: {notion_url}"
        )

    description = "\n".join(
        description_parts
    )

    # Stable UID:
    # same Notion item keeps the same Apple Calendar event.
    uid = (
        page["id"]
        .replace("-", "")
        + "-"
        + platform.lower()
        + "@chloe-content-calendar"
    )

    last_edited = to_ics_timestamp(
        page.get("last_edited_time")
    )

    created = to_ics_timestamp(
        page.get("created_time")
    )

    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{last_edited}",
        f"CREATED:{created}",
        f"LAST-MODIFIED:{last_edited}",
        f"DTSTART;VALUE=DATE:{to_ics_date(start)}",
        f"DTEND;VALUE=DATE:{end_exclusive}",
        f"SUMMARY:{escape_ics_text(summary)}",
    ]

    if description:
        lines.append(
            "DESCRIPTION:"
            + escape_ics_text(
                description
            )
        )

    if notion_url:
        lines.append(
            f"URL:{notion_url}"
        )

    lines.extend([
        "TRANSP:TRANSPARENT",
        "STATUS:CONFIRMED",
        "END:VEVENT",
    ])

    return lines


# =========================================================
# GENERATE ONE PLATFORM CALENDAR
# =========================================================

def generate_calendar(pages, platform):
    relevant_pages = []

    for page in pages:
        post_date = get_post_date(
            page
        )

        if (
            not post_date
            or not post_date.get("start")
        ):
            continue

        platforms = [
            p.strip().upper()
            for p in get_platforms(page)
        ]

        if platform not in platforms:
            continue

        relevant_pages.append(page)

    # Sort chronologically
    relevant_pages.sort(
        key=lambda page:
        get_post_date(page)["start"][:10]
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Chloe//Notion Content Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{platform} Content",
        "X-PUBLISHED-TTL:PT1H",
    ]

    for page in relevant_pages:
        event_lines = make_event(
            page,
            platform
        )

        if event_lines:
            lines.extend(
                event_lines
            )

    lines.append(
        "END:VCALENDAR"
    )

    # Fold long lines and use proper CRLF endings.
    folded_lines = [
        fold_ics_line(line)
        for line in lines
    ]

    return (
        "\r\n".join(
            folded_lines
        )
        + "\r\n"
    )


# =========================================================
# MAIN
# =========================================================

def main():
    print(
        "Reading Notion database..."
    )

    pages = query_notion()

    print(
        f"Found {len(pages)} Notion pages."
    )

    os.makedirs(
        "output",
        exist_ok=True
    )

    for platform in PLATFORMS:
        calendar = generate_calendar(
            pages,
            platform
        )

        filename = (
            "output/"
            + platform.lower()
            + ".ics"
        )

        with open(
            filename,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:
            file.write(
                calendar
            )

        print(
            f"Created {filename}"
        )

    print(
        "Done!"
    )


if __name__ == "__main__":
    main()
