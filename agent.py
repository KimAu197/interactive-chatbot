import json
import logging
import os
from datetime import datetime, timezone
from openai import OpenAI
from dotenv import load_dotenv
import cal_api

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are a helpful scheduling assistant that manages cal.com bookings.
Today's date is {today}. The host's timezone is America/New_York.

Available meeting types:
- 15-minute meeting (event type ID: 5011766)
- 30-minute meeting (event type ID: 5011767)

When helping users:
- For booking: collect name, email, preferred date/time, and duration (15 or 30 min). Always check available slots first.
- For listing: ask for their email to find their bookings.
- For cancelling: find the booking by email and time, then cancel using the booking UID.
- For rescheduling: find the booking first, then check new slot availability, then reschedule.
- Always confirm before taking destructive actions (cancel/reschedule).
- Present times in a human-friendly format; ask for the user's timezone if they mention local times.
- When checking slots, search a 7-day window from the requested date."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": "Get available time slots for a meeting type within a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type_id": {
                        "type": "integer",
                        "description": "Event type ID: 5011766 for 15-min, 5011767 for 30-min meetings.",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format.",
                    },
                },
                "required": ["event_type_id", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bookings",
            "description": "List scheduled bookings, optionally filtered by attendee email and status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "attendee_email": {
                        "type": "string",
                        "description": "Email address of the attendee to filter by.",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["upcoming", "past", "cancelled", "all"],
                        "description": "Filter by booking status. Defaults to 'upcoming'.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Create a new booking/meeting on cal.com.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type_id": {
                        "type": "integer",
                        "description": "Event type ID: 5011766 for 15-min, 5011767 for 30-min meetings.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "Meeting start time in ISO 8601 UTC format, e.g. '2026-03-13T14:00:00Z'.",
                    },
                    "attendee_name": {
                        "type": "string",
                        "description": "Full name of the person booking the meeting.",
                    },
                    "attendee_email": {
                        "type": "string",
                        "description": "Email address of the attendee.",
                    },
                    "attendee_timezone": {
                        "type": "string",
                        "description": "IANA timezone of the attendee, e.g. 'America/New_York'.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional meeting reason or notes.",
                    },
                },
                "required": [
                    "event_type_id",
                    "start_time",
                    "attendee_name",
                    "attendee_email",
                    "attendee_timezone",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_booking",
            "description": "Cancel an existing booking by its UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {
                        "type": "string",
                        "description": "The unique identifier (UID) of the booking to cancel.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for cancellation.",
                    },
                },
                "required": ["booking_uid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_booking",
            "description": "Reschedule an existing booking to a new date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_uid": {
                        "type": "string",
                        "description": "The unique identifier (UID) of the booking to reschedule.",
                    },
                    "new_start_time": {
                        "type": "string",
                        "description": "New start time in ISO 8601 UTC format, e.g. '2026-03-14T15:00:00Z'.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason for rescheduling.",
                    },
                },
                "required": ["booking_uid", "new_start_time"],
            },
        },
    },
]


def _dispatch_tool(name: str, args: dict) -> str:
    """Execute a tool call and return the result as a JSON string."""
    logger.info("Tool call: %s args=%s", name, args)
    try:
        if name == "get_available_slots":
            result = cal_api.get_available_slots(**args)
        elif name == "list_bookings":
            result = cal_api.list_bookings(**args)
        elif name == "create_booking":
            result = cal_api.create_booking(**args)
        elif name == "cancel_booking":
            result = cal_api.cancel_booking(**args)
        elif name == "generate_booking_link":
            result = cal_api.generate_booking_link(**args)
        elif name == "reschedule_booking":
            result = cal_api.reschedule_booking(**args)
        else:
            result = {"error": f"Unknown tool: {name}"}
        logger.debug("Tool result: %s -> %s", name, str(result)[:300])
    except Exception as e:
        logger.error("Tool error: %s raised %s: %s", name, type(e).__name__, e)
        result = {"error": str(e)}
    return json.dumps(result, default=str)


def run_agent(messages: list) -> tuple[str, list]:
    """Run one turn of the agent, handling any tool calls.

    Args:
        messages: Full conversation history including the latest user message.

    Returns:
        Tuple of (assistant_reply_text, updated_messages).
    """
    today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
    system_message = {"role": "system", "content": SYSTEM_PROMPT.format(today=today)}
    full_messages = [system_message] + messages

    while True:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        message = response.choices[0].message

        if message.tool_calls:
            full_messages.append(message)

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool_result = _dispatch_tool(tool_name, tool_args)

                full_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )
        else:
            reply = message.content or ""
            messages.append({"role": "assistant", "content": reply})
            return reply, messages
