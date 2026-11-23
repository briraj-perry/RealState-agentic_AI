"""Native Apple Calendar bridge for the local macOS dashboard."""

import asyncio
import subprocess
import sys
from threading import Lock

from fastapi import HTTPException
from pydantic import ValidationError

from estate_ai.db import Audit, Property, TestSession
from estate_ai.schemas import VisitArgs, validate_visit_date

_calendar_lock = Lock()


def available():
    return sys.platform == "darwin"


def run_calendar(script, *args):
    if not available():
        raise HTTPException(409, "Apple Calendar requires the dashboard server to run on a Mac.")
    try:
        return subprocess.run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", script, *args],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        if "(-1743)" in exc.stderr:
            raise HTTPException(
                503, "Allow Calendar access under System Settings → Privacy & Security → Automation."
            ) from exc
        raise HTTPException(503, "Apple Calendar could not complete the request. Try again.") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(503, "Apple Calendar did not respond. Open Calendar and try again.") from exc


def check_connection():
    run_calendar('Application("Calendar").calendars.name().length')
    return {"connected": True}


def visit_details(proposal):
    try:
        details = VisitArgs.model_validate_json(proposal.payload)
        validate_visit_date(details.start_time)
    except ValidationError as exc:
        raise HTTPException(422, "The visit needs a valid date and time with a time zone.") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return details


async def save_visit(session, proposal):
    if proposal.calendar_state == "saved":
        return {"status": "already_added"}
    details = visit_details(proposal)
    listing = session.get(Property, details.property_id)
    title = listing.title if listing else details.property_id
    if session.get(TestSession, proposal.phone):
        title = "Test · " + title
    result = await asyncio.to_thread(add_visit, proposal, title)
    proposal.calendar_state = "saved"
    session.add(
        Audit(
            phone=proposal.phone,
            action="calendar_saved",
            detail=f"Visit request for {title} saved to Apple Calendar.",
        )
    )
    return result


def add_visit(proposal, property_title):
    script = """
    function run([reference, title, timestamp]) {
        const app = Application("Calendar");
        const name = "Estate AI Visits";
        let calendar = app.calendars.byName(name);
        if (!calendar.exists()) {
            app.calendars.push(app.Calendar({name: name}));
            calendar = app.calendars.byName(name);
        }
        if (!calendar.writable()) return "read_only";
        const description = "Site visit request · " + reference;
        const matches = calendar.events.whose({description: description})();
        if (matches.length) return "already_added";
        const start = new Date(Number(timestamp));
        calendar.events.push(app.Event({
            summary: title, description: description,
            startDate: start, endDate: new Date(start.getTime() + 3600000)
        }));
        try {
            const notifier = Application.currentApplication();
            notifier.includeStandardAdditions = true;
            notifier.displayNotification(title + " · " + start.toLocaleString(), {withTitle: "Visit saved to Apple Calendar"});
        } catch (error) {
            // Calendar accepted the event even if macOS could not show a notification.
        }
        return "added";
    }
    """
    with _calendar_lock:
        start = visit_details(proposal).start_time
        status = run_calendar(
            script,
            proposal.id,
            "Requested site visit · " + property_title,
            str(int(start.timestamp() * 1000)),
        )
    if status == "read_only":
        raise HTTPException(503, "The Estate AI Visits calendar is read-only.")
    if status not in {"added", "already_added"}:
        raise HTTPException(503, "Apple Calendar could not confirm the event. Try again.")
    return {"status": status}
