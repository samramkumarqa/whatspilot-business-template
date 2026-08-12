from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from auth import enforce_tenant_access, enforce_tenant_access_for_customer
from crm.customer_mapping import get_business_phone_by_user
from database.db import get_crm_connection
from reminder_manager import (
    find_stale_reminders,
    delete_stale_reminders,
    complete_reminder,
    get_reminder_customer_phone,
)

router = APIRouter()

APP_DB = "data/app.db"   # use your existing DB path


def get_connection():
    # Shares the pooled data/app.db connections from database/db.py instead
    # of opening its own unpooled sqlite3 connection to the same file.
    return get_crm_connection()

# NOTE: this file previously also defined GET /reminders here
# (get_all_reminders()). api/misc.py registers the exact same path, and
# since misc_router is included before reminders_router in main.py,
# misc.py's handler always won - this one was dead, unreachable code.
# Removed; misc.py's GET /reminders (backed by reminder_manager.get_reminders())
# is the one that actually serves that path.

# =====================================================
# STALE REMINDERS (preview + cleanup)
#
# These have to be registered before GET /reminders/{customer_phone}
# below - otherwise FastAPI would match "/reminders/stale" against that
# route's {customer_phone} path parameter (literally looking up a
# customer named "stale") instead of reaching these.
# =====================================================

async def _business_phone_for(user_id: str, request: Request) -> str | None:
    """
    Shared by the /reminders/stale routes below: verifies the session is
    allowed to see `user_id`'s data, then resolves it to a business_phone
    for scoping the reminders query.
    """

    enforce_tenant_access(request, user_id)

    return await run_in_threadpool(get_business_phone_by_user, user_id)


@router.get("/reminders/stale")
async def preview_stale_reminders(user_id: str, request: Request):
    """
    Reminders whose originating rule has since been deleted, no longer
    has a Create Reminder action, or now says something different - i.e.
    the reminder text on screen no longer reflects the rule's real,
    current configuration. Scoped to the requesting business - requires
    user_id and checks it against the session first.
    """

    business_phone = await _business_phone_for(user_id, request)

    if not business_phone:
        return {"stale": []}

    return {
        "stale": await run_in_threadpool(find_stale_reminders, business_phone)
    }


@router.delete("/reminders/stale")
async def clear_stale_reminders(user_id: str, request: Request):

    business_phone = await _business_phone_for(user_id, request)

    if not business_phone:
        return {
            "status": "success",
            "deleted": 0
        }

    deleted = await run_in_threadpool(delete_stale_reminders, business_phone)

    return {
        "status": "success",
        "deleted": deleted
    }

# =====================================================
# MARK A REMINDER DONE
#
# 3 path segments (/reminders/{id}/complete), so this never collides with
# GET /reminders/{customer_phone} below (2 segments) regardless of
# registration order.
# =====================================================

@router.post("/reminders/{reminder_id}/complete")
async def mark_reminder_complete(reminder_id: int, request: Request):
    """
    A reminder id alone doesn't say which business owns it, so this looks
    up the owning customer_phone first and checks it against the session
    via enforce_tenant_access_for_customer() - previously any logged-in
    business owner could mark any other business's reminder complete by
    guessing/incrementing ids.
    """

    customer_phone = await run_in_threadpool(get_reminder_customer_phone, reminder_id)

    if customer_phone is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    await enforce_tenant_access_for_customer(request, customer_phone)

    await run_in_threadpool(complete_reminder, reminder_id)

    return {
        "status": "success"
    }

# =====================================================
# GET REMINDERS FOR ONE CUSTOMER
# =====================================================

def _fetch_customer_reminders(customer_phone: str):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""

        SELECT *

        FROM reminders

        WHERE customer_phone = ?
        AND completed = 0

        ORDER BY due_date ASC

    """, (customer_phone,))

    reminders = [
        dict(row)
        for row in cursor.fetchall()
    ]

    conn.close()

    return reminders


@router.get("/reminders/{customer_phone}")
async def get_customer_reminders(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    reminders = await run_in_threadpool(_fetch_customer_reminders, customer_phone)

    return {
        "reminders": reminders
    }