import logging
import os
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CAL_API_KEY = os.getenv("CAL_API_KEY")
CAL_BASE_URL = "https://api.cal.com/v2"
CAL_HOST_TIMEZONE = os.getenv("CAL_HOST_TIMEZONE", "America/New_York")

# Available event types on this cal.com account
EVENT_TYPES = {
    "15min": {"id": 5011766, "title": "15 min meeting", "duration": 15},
    "30min": {"id": 5011767, "title": "30 min meeting", "duration": 30},
}

HEADERS = {
    "Authorization": f"Bearer {CAL_API_KEY}",
    "Content-Type": "application/json",
    "cal-api-version": "2024-08-13",
}


def _handle_response(response: requests.Response) -> dict:
    logger.debug("%s %s -> %d", response.request.method, response.url, response.status_code)
    try:
        data = response.json()
    except Exception:
        logger.error("Non-JSON response from %s: %s", response.url, response.text[:500])
        response.raise_for_status()
        return {}
    if response.status_code >= 400:
        msg = data.get("message") or data.get("error") or response.text
        logger.error(
            "Cal.com API error %d on %s %s: %s",
            response.status_code,
            response.request.method,
            response.url,
            msg,
        )
        raise ValueError(f"Cal.com API error ({response.status_code}): {msg}")
    return data


def get_available_slots(event_type_id: int, start_date: str, end_date: str) -> dict:
    """Return available slots for an event type within a date range.

    Args:
        event_type_id: The cal.com event type ID.
        start_date: ISO 8601 date string, e.g. "2026-03-12".
        end_date: ISO 8601 date string, e.g. "2026-03-19".

    Returns:
        Dict mapping date strings to lists of available time slot ISO strings.
    """
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    params = {
        "startTime": start_iso,
        "endTime": end_iso,
        "eventTypeId": event_type_id,
    }
    logger.info("get_available_slots: event_type_id=%d %s to %s", event_type_id, start_date, end_date)
    response = requests.get(f"{CAL_BASE_URL}/slots/available", headers=HEADERS, params=params)
    data = _handle_response(response)
    slots_raw = data.get("data", {}).get("slots", {})
    result = {}
    for date_key, slots in slots_raw.items():
        result[date_key] = [s["time"] for s in slots]
    return result


def list_bookings(attendee_email: str | None = None, status: str | None = None) -> list:
    """List bookings, optionally filtered by attendee email or status.

    Args:
        attendee_email: Filter bookings by this attendee email.
        status: One of "upcoming", "past", "cancelled", "all". Defaults to "upcoming".

    Returns:
        List of booking dicts.
    """
    params = {}
    if attendee_email:
        params["attendeeEmail"] = attendee_email
    if status and status != "all":
        params["status"] = status
    logger.info("list_bookings: attendee_email=%s status=%s", attendee_email, status)
    response = requests.get(f"{CAL_BASE_URL}/bookings", headers=HEADERS, params=params)
    data = _handle_response(response)
    raw = data.get("data", [])
    # API returns data as a list directly
    if isinstance(raw, list):
        return raw
    return raw.get("bookings", [])


def create_booking(
    event_type_id: int,
    start_time: str,
    attendee_name: str,
    attendee_email: str,
    attendee_timezone: str,
    notes: str | None = None,
) -> dict:
    """Create a new booking.

    Args:
        event_type_id: The cal.com event type ID (5011766 for 15min, 5011767 for 30min).
        start_time: ISO 8601 datetime string, e.g. "2026-03-13T14:00:00Z".
        attendee_name: Full name of the attendee.
        attendee_email: Email address of the attendee.
        attendee_timezone: IANA timezone string, e.g. "America/New_York".
        notes: Optional meeting notes or reason.

    Returns:
        The created booking dict.
    """
    payload = {
        "eventTypeId": event_type_id,
        "start": start_time,
        "attendee": {
            "name": attendee_name,
            "email": attendee_email,
            "timeZone": attendee_timezone,
            "language": "en",
        },
        "metadata": {},
    }
    if notes:
        payload["bookingFieldsResponses"] = {"notes": notes}

    logger.info(
        "create_booking: event_type_id=%d start=%s attendee=%s <%s>",
        event_type_id, start_time, attendee_name, attendee_email,
    )
    logger.debug("create_booking payload: %s", payload)
    response = requests.post(f"{CAL_BASE_URL}/bookings", headers=HEADERS, json=payload)
    data = _handle_response(response)
    return data.get("data", data)


def cancel_booking(booking_uid: str, reason: str | None = None) -> dict:
    """Cancel an existing booking.

    Args:
        booking_uid: The unique ID of the booking to cancel.
        reason: Optional cancellation reason.

    Returns:
        The cancellation response dict.
    """
    payload = {
        "cancellationReason": reason or "Cancelled via chatbot",
        "cancelSubsequentBookings": False,
    }
    logger.info("cancel_booking: uid=%s reason=%s", booking_uid, reason)
    response = requests.post(
        f"{CAL_BASE_URL}/bookings/{booking_uid}/cancel",
        headers=HEADERS,
        json=payload,
    )
    data = _handle_response(response)
    return data.get("data", data)


def reschedule_booking(
    booking_uid: str,
    new_start_time: str,
    reason: str | None = None,
) -> dict:
    """Reschedule an existing booking to a new time.

    Args:
        booking_uid: The unique ID of the booking to reschedule.
        new_start_time: New ISO 8601 datetime string, e.g. "2026-03-14T15:00:00Z".
        reason: Optional rescheduling reason.

    Returns:
        The rescheduled booking dict.
    """
    payload = {
        "start": new_start_time,
        "rescheduledBy": "attendee",
        "reschedulingReason": reason or "Rescheduled via chatbot",
    }
    logger.info("reschedule_booking: uid=%s new_start=%s", booking_uid, new_start_time)
    response = requests.post(
        f"{CAL_BASE_URL}/bookings/{booking_uid}/reschedule",
        headers=HEADERS,
        json=payload,
    )
    data = _handle_response(response)
    return data.get("data", data)


def get_event_type_id(duration_minutes: int) -> int:
    """Return the event type ID for the given meeting duration (15 or 30 minutes)."""
    if duration_minutes <= 15:
        return EVENT_TYPES["15min"]["id"]
    return EVENT_TYPES["30min"]["id"]


def format_booking_summary(booking: dict) -> str:
    """Return a human-readable one-line summary of a booking."""
    title = booking.get("title", "Meeting")
    start = booking.get("startTime", "")
    uid = booking.get("uid", "")
    attendees = booking.get("attendees", [])
    attendee_str = ", ".join(a.get("name", "") for a in attendees if a.get("name"))
    if start:
        try:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            start = dt.strftime("%b %d, %Y at %I:%M %p UTC")
        except ValueError:
            pass
    return f"[{uid[:8]}] {title} — {start} — Attendees: {attendee_str}"
