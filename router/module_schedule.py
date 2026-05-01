"""Human-readable module schedule parsing for Chuck the Framework."""

from __future__ import annotations

import re


_WEEKDAYS = {
    "sunday": 0,
    "sun": 0,
    "monday": 1,
    "mon": 1,
    "tuesday": 2,
    "tue": 2,
    "wednesday": 3,
    "wed": 3,
    "thursday": 4,
    "thu": 4,
    "friday": 5,
    "fri": 5,
    "saturday": 6,
    "sat": 6,
}


def _parse_time(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError("time must be HH:MM in 24-hour time")
    return int(match.group(1)), int(match.group(2))


def human_schedule_to_cron(schedule_text: str) -> str:
    """Convert the supported human schedule grammar to a cron expression.

    The grammar is intentionally small so module authors do not need cron
    training, while the framework still produces deterministic Toolforge/K8s
    schedules:

    - every N minutes
    - every N hours
    - every hour
    - daily at HH:MM
    - weekly on monday at HH:MM
    - monthly on day 1 at HH:MM
    """
    text = " ".join(str(schedule_text or "").strip().lower().split())
    if not text:
        raise ValueError("run schedule is required")

    match = re.fullmatch(r"every (\d+) minutes?", text)
    if match:
        minutes = int(match.group(1))
        if minutes <= 0 or minutes > 59:
            raise ValueError("minute interval must be between 1 and 59")
        return f"*/{minutes} * * * *"

    match = re.fullmatch(r"every (\d+) hours?", text)
    if match:
        hours = int(match.group(1))
        if hours <= 0 or hours > 23:
            raise ValueError("hour interval must be between 1 and 23")
        return f"0 */{hours} * * *"

    if text == "every hour":
        return "0 * * * *"

    match = re.fullmatch(r"daily at (\S+)", text)
    if match:
        hour, minute = _parse_time(match.group(1))
        return f"{minute} {hour} * * *"

    match = re.fullmatch(r"weekly on ([a-z]+) at (\S+)", text)
    if match:
        weekday = match.group(1)
        if weekday not in _WEEKDAYS:
            raise ValueError(f"unknown weekday: {weekday}")
        hour, minute = _parse_time(match.group(2))
        return f"{minute} {hour} * * {_WEEKDAYS[weekday]}"

    match = re.fullmatch(r"monthly on day (\d{1,2}) at (\S+)", text)
    if match:
        day = int(match.group(1))
        if day <= 0 or day > 31:
            raise ValueError("monthly day must be between 1 and 31")
        hour, minute = _parse_time(match.group(2))
        return f"{minute} {hour} {day} * *"

    raise ValueError(
        "unsupported run schedule; use forms like 'every 15 minutes', "
        "'daily at 03:00', or raw cron in schedule"
    )

