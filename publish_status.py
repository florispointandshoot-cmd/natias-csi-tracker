#!/usr/bin/env python3
"""Schrijf een anonieme werklijst: weekdag, datum, Brussel of Antwerpen, uren.

Geen klantnamen, geen adressen, geen privé-afspraken.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).resolve().parent
BRUSSELS = dt.timezone(dt.timedelta(hours=1))  # vervangen zodra zoneinfo geladen is
try:
    from zoneinfo import ZoneInfo

    BRUSSELS = ZoneInfo("Europe/Brussels")
except Exception:
    pass

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
WEEKDAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
MONTHS_NL = [
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
]
# Vanaf vandaag tot einde van de volgende maand (bv. 29 okt → 30 nov).
HORIZON_DAYS = 62
MERGE_GAP = dt.timedelta(minutes=45)
HEARTBEAT = dt.timedelta(hours=12)

# Woorden die nooit op de publieke pagina mogen staan.
FORBIDDEN = (
    "proximus",
    "dazn",
    "eleven",
    "atv",
    "tvoost",
    "tvoost",
    "vrt",
    "solvus",
    "floris",
    "rijnkaai",
    "reyers",
    "evere",
    "stroobants",
    "@",
)


def token_path() -> Path:
    return Path(os.environ.get("TOKEN_PATH", ROOT.parent / "token.json"))


def calendar_service():
    path = token_path()
    if not path.exists():
        sys.exit(f"Geen agenda-token gevonden op {path}")
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json())
        else:
            sys.exit("Agenda-token is verlopen. Vernieuw token.json lokaal.")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def fetch_events(service, start: dt.date, end: dt.date) -> list[dict]:
    time_min = dt.datetime.combine(start, dt.time.min, tzinfo=BRUSSELS)
    time_max = dt.datetime.combine(end, dt.time.max, tzinfo=BRUSSELS)
    items: list[dict] = []
    page_token = None
    while True:
        kwargs = {
            "calendarId": "primary",
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": 2500,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.events().list(**kwargs).execute()
        items.extend(result.get("items", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return items


def event_text(event: dict) -> str:
    return f"{event.get('summary') or ''} {event.get('description') or ''}".lower()


def is_work(event: dict) -> bool:
    if event.get("status") == "cancelled":
        return False
    text = event_text(event)
    if "teammeeting" in text:
        return False
    keys = (
        "proximus",
        "dazn",
        "eleven",
        "atv",
        "tvoost",
        "vrt",
        "chef techniek",
        "woz",
        "media manager",
        "eindregie",
        "overuur",
    )
    return any(key in text for key in keys)


def city_of(event: dict) -> str | None:
    location = (event.get("location") or "").lower()
    if "antwerp" in location or "antwerpen" in location:
        return "Antwerpen"
    if any(name in location for name in ("brussel", "brussels", "evere", "schaarbeek", "schaerbeek")):
        return "Brussel"
    text = event_text(event)
    if any(key in text for key in ("atv", "tvoost")):
        return "Antwerpen"
    if any(key in text for key in ("dazn", "eleven", "proximus", "vrt")):
        return "Brussel"
    return None


def parse_title_clock(summary: str) -> tuple[dt.time, dt.time] | None:
    text = (summary or "").lower().replace("u", "h")
    match = re.search(
        r"(\d{1,2})h(\d{2})?\s*[-–]\s*(\d{1,2})h(\d{2})?",
        text,
    )
    if not match:
        match = re.search(
            r"(\d{1,2})h(\d{2})?\s+(\d{1,2})h(\d{2})?",
            text,
        )
    if not match:
        return None
    start_h, start_m = int(match.group(1)), int(match.group(2) or 0)
    end_h, end_m = int(match.group(3)), int(match.group(4) or 0)
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23 and start_m < 60 and end_m < 60):
        return None
    return dt.time(start_h, start_m), dt.time(end_h, end_m)


def as_brussels(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BRUSSELS)
    return parsed.astimezone(BRUSSELS)


def event_day(event: dict) -> dt.date | None:
    start_raw = event.get("start") or {}
    if start_raw.get("dateTime"):
        return as_brussels(start_raw["dateTime"]).date()
    if start_raw.get("date"):
        return dt.date.fromisoformat(start_raw["date"][:10])
    return None


def fixed_clocks(event: dict) -> tuple[dt.time, dt.time] | None:
    """Vaste uren voor ATV/TVOOST; agenda-eindtijden kloppen daar niet altijd."""
    text = event_text(event)
    summary = (event.get("summary") or "").lower().replace("u", "h")
    day = event_day(event)

    if "tvoost" in text or "eindregie" in text:
        return dt.time(14, 0), dt.time(19, 0)

    if "dazn" in text or "eleven" in text or "media manager" in text:
        return dt.time(10, 0), dt.time(18, 0)

    if any(key in text for key in ("atv", "chef techniek", "woz")):
        if "woz" in summary:
            return dt.time(8, 30), dt.time(19, 30)
        weekend = bool(day and day.weekday() >= 5)
        day_shift = "14h30" in summary or "14:30" in summary or weekend
        if day_shift:
            return dt.time(14, 30), dt.time(19, 30)
        return dt.time(10, 45), dt.time(19, 30)

    return None


def shift_bounds(event: dict) -> tuple[dt.datetime, dt.datetime] | None:
    day = event_day(event)
    if not day:
        return None

    clocks = fixed_clocks(event)
    if clocks:
        start = dt.datetime.combine(day, clocks[0], tzinfo=BRUSSELS)
        end = dt.datetime.combine(day, clocks[1], tzinfo=BRUSSELS)
        if end <= start:
            end += dt.timedelta(days=1)
        return start, end

    start_raw = event.get("start") or {}
    end_raw = event.get("end") or {}
    if start_raw.get("dateTime") and end_raw.get("dateTime"):
        start = as_brussels(start_raw["dateTime"])
        end = as_brussels(end_raw["dateTime"])
        if end > start:
            return start, end
        return None

    clocks = parse_title_clock(event.get("summary") or "")
    if not clocks:
        return None
    start = dt.datetime.combine(day, clocks[0], tzinfo=BRUSSELS)
    end = dt.datetime.combine(day, clocks[1], tzinfo=BRUSSELS)
    if end <= start:
        end += dt.timedelta(days=1)
    return start, end


class Shift:
    def __init__(self, start: dt.datetime, end: dt.datetime, city: str | None):
        self.start = start
        self.end = end
        self.city = city


def attach_missing_cities(shifts: list[Shift]) -> list[Shift]:
    for index, shift in enumerate(shifts):
        if shift.city:
            continue
        for earlier in range(index - 1, -1, -1):
            other = shifts[earlier]
            if other.city and shift.start - other.end <= dt.timedelta(hours=2):
                shift.city = other.city
                break
        if shift.city:
            continue
        for later in range(index + 1, len(shifts)):
            other = shifts[later]
            if other.city and other.start - shift.end <= dt.timedelta(hours=2):
                shift.city = other.city
                break
    return [shift for shift in shifts if shift.city]


def merge_shifts(shifts: list[Shift]) -> list[Shift]:
    merged: list[Shift] = []
    for shift in shifts:
        if (
            merged
            and merged[-1].city == shift.city
            and shift.start - merged[-1].end <= MERGE_GAP
        ):
            merged[-1].end = max(merged[-1].end, shift.end)
            continue
        merged.append(shift)
    return merged


def fmt_u(moment: dt.datetime) -> str:
    """Altijd minuten tonen (14u00, 19u30), zodat 18 en 00 niet wegvallen."""
    local = moment.astimezone(BRUSSELS)
    hour = "00" if local.hour == 0 else str(local.hour)
    return f"{hour}u{local.minute:02d}"


def horizon_end(today: dt.date) -> dt.date:
    """Einde van de volgende kalendermaand (29 okt → 30 nov)."""
    if today.month == 12:
        year, month = today.year + 1, 1
    else:
        year, month = today.year, today.month + 1
    if month == 12:
        return dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)


def build_days(events: list[dict], today: dt.date) -> list[dict]:
    until = horizon_end(today)
    shifts: list[Shift] = []
    for event in events:
        if not is_work(event):
            continue
        bounds = shift_bounds(event)
        if not bounds:
            continue
        start, end = bounds
        day = start.astimezone(BRUSSELS).date()
        if day < today or day > until:
            continue
        shifts.append(Shift(start, end, city_of(event)))

    shifts.sort(key=lambda item: item.start)
    shifts = merge_shifts(attach_missing_cities(shifts))

    grouped: dict[str, list[Shift]] = {}
    for shift in shifts:
        key = shift.start.astimezone(BRUSSELS).date().isoformat()
        if shift.start.astimezone(BRUSSELS).date() < today:
            continue
        grouped.setdefault(key, []).append(shift)

    days = []
    cursor = today
    while cursor <= until:
        key = cursor.isoformat()
        work = grouped.get(key, [])
        rows = [
            {
                "city": shift.city,
                "uren": f"{fmt_u(shift.start)}-{fmt_u(shift.end)}",
                "start": shift.start.isoformat(),
                "end": shift.end.isoformat(),
            }
            for shift in work
        ]
        days.append(
            {
                "date": key,
                "weekday": WEEKDAYS[cursor.weekday()],
                "datum": cursor.strftime("%d/%m"),
                "month": MONTHS_NL[cursor.month - 1],
                "year": cursor.year,
                "available": not rows,
                "shifts": rows,
            }
        )
        cursor += dt.timedelta(days=1)
    return days


def line_for(day: dict) -> str:
    if day.get("available"):
        return f"{day['weekday']} {day['datum']}: AVAILABLE"
    parts = [f"{shift['city']}: {shift['uren']}" for shift in day["shifts"]]
    return f"{day['weekday']} {day['datum']}: {', '.join(parts)}"


def assert_anonymous(payload: dict) -> None:
    blob = json.dumps(payload, ensure_ascii=False).lower()
    for word in FORBIDDEN:
        if word in blob:
            sys.exit(f"Publicatie gestopt: de pagina zou '{word}' tonen.")


def write_outputs(payload: dict) -> None:
    status_path = ROOT / "status.json"
    html_path = ROOT / "index.html"
    status_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    html = html_path.read_text()
    pattern = re.compile(
        r'(<script id="status" type="application/json">)(.*?)(</script>)',
        re.S,
    )
    if not pattern.search(html):
        sys.exit("index.html mist het status-blok.")
    new_html = pattern.sub(
        lambda match: match.group(1) + status_text.strip() + match.group(3),
        html,
        count=1,
    )
    previous = status_path.read_text() if status_path.exists() else ""
    if previous == status_text and html == new_html:
        print("Rooster ongewijzigd.")
        return
    status_path.write_text(status_text)
    html_path.write_text(new_html)


def maybe_keep_timestamp(payload: dict) -> dict:
    status_path = ROOT / "status.json"
    if not status_path.exists():
        return payload
    try:
        old = json.loads(status_path.read_text())
    except json.JSONDecodeError:
        return payload
    if old.get("days") != payload["days"]:
        return payload
    try:
        updated = dt.datetime.fromisoformat(old["updated"])
    except (KeyError, ValueError):
        return payload
    if dt.datetime.now(BRUSSELS) - updated < HEARTBEAT:
        payload["updated"] = old["updated"]
    return payload


def main() -> None:
    today = dt.datetime.now(BRUSSELS).date()
    service = calendar_service()
    events = fetch_events(service, today - dt.timedelta(days=1), horizon_end(today))
    payload = {
        "updated": dt.datetime.now(BRUSSELS).replace(microsecond=0).isoformat(),
        "days": build_days(events, today),
    }
    payload = maybe_keep_timestamp(payload)
    assert_anonymous(payload)
    write_outputs(payload)
    if not payload["days"]:
        print("Geen werkdagen in de komende weken.")
        return
    for day in payload["days"]:
        print(line_for(day))


if __name__ == "__main__":
    main()
