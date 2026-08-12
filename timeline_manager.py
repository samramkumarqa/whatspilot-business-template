from crm.activity_manager import get_activity
from crm.lead_manager import get_lead_timeline


def get_customer_timeline(customer_phone):
    """
    One merged, chronological view of everything that's happened with a
    customer, combining two tables that used to be shown in separate
    dashboard panels ("Lead Journey" and "Activity Log"):

      - lead_history (crm/lead_manager.py) - a row is written every time
        update_lead_intelligence() runs, which is on EVERY incoming
        WhatsApp message, whether or not the status actually changed.
        Only rows where the status differs from the immediately
        preceding one represent a real event; the rest are just noise
        from re-analysing messages that didn't move the needle.

      - ai_activity (crm/activity_manager.py) - opportunities, tag
        updates, sales coach tips, reminders scheduled, and manual notes.
        Entries logged by the "Add CRM Activity" automation rule action
        (activity_type "Automation") are deliberately excluded here - just
        generic, user-typed boilerplate with no real signal, unlike the
        AI-driven entries. They're still written to ai_activity and
        readable via GET /activity/{phone} if needed elsewhere; they're
        just not part of this merged view.

    A genuine status change writes to BOTH tables at essentially the same
    moment: update_lead_intelligence() inserts a lead_history row and (via
    ai/lead_intelligence.py's "changed" check, which is always true when
    status changes) also logs an "AI - Customer Intelligence Updated"
    ai_activity row whose `details` already includes the new status. A
    manual save behaves the same way (see POST /lead in api/customer.py).
    So once the lead_history row has been filtered down to real
    transitions, any transition that has a matching ai_activity row at the
    same timestamp is dropped in favor of that richer entry, instead of
    showing the same event twice.
    """

    # ---- lead_history: keep only real status transitions ----------------

    history_newest_first = get_lead_timeline(customer_phone)
    history_oldest_first = list(reversed(history_newest_first))

    status_changes = []
    last_status = None

    for item in history_oldest_first:

        if item["status"] != last_status:
            status_changes.append(item)

        last_status = item["status"]

    # ---- ai_activity -------------------------------------------------
    # "Automation" entries (the "Add CRM Activity" rule action) are left
    # out of this merged timeline - see the module docstring.

    activity = [
        a for a in get_activity(customer_phone)
        if a["activity_type"] != "Automation"
    ]

    activity_timestamps = {
        (a["created_at"], a["activity_type"])
        for a in activity
    }

    def _already_covered_by_activity(status_item):
        # A real status change is always paired with either an "AI" or
        # "Manual" ai_activity row logged in the same request, at the
        # same created_at second.
        return (
            (status_item["created_at"], "AI") in activity_timestamps
            or (status_item["created_at"], "Manual") in activity_timestamps
        )

    timeline = []

    for item in status_changes:

        if _already_covered_by_activity(item):
            continue

        timeline.append({
            "type": "status_change",
            "date": item["created_at"],
            "activity_type": item["updated_by"] or "System",
            "title": f"Status: {item['status']}",
            "details": item["reason"] or ""
        })

    for item in activity:

        timeline.append({
            "type": "activity",
            "date": item["created_at"],
            "activity_type": item["activity_type"],
            "title": item["title"],
            "details": item["details"]
        })

    timeline.sort(
        key=lambda entry: entry["date"] or "",
        reverse=True
    )

    return timeline
