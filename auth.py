"""
Session/auth helpers:

- enforce_tenant_access() - the security boundary for the logged-in
  business owner. Every API route that takes a `user_id` path param
  calls this first; it's what stops a logged-in business owner from
  viewing another business's data by editing a URL or replaying a
  request with a different user_id, regardless of what the frontend's
  hidden input happens to send. (In practice this deployment only ever
  has one business's data in reach at all - see api/auth.py's
  BUSINESS_ID check at login - but this stays as defense in depth rather
  than assuming the login gate is the only thing standing between a
  request and another business's rows.)

- resolve_dashboard_user_id() - picks which business's dashboard/
  analytics/settings pages should render for the current session: always
  the logged-in business owner's own business.
"""

from fastapi import HTTPException, Request


def enforce_tenant_access(request: Request, user_id: str) -> None:
    """
    Raises 403 unless the current session's business_owner user_id
    matches `user_id`. Checked against request.session, not anything the
    client sent, so it can't be bypassed by editing the hidden #userId
    input or hand-crafting an API call with a different user_id in the
    URL.

    Call this as the first line of every route that takes `user_id` as
    a path param.
    """

    if request.session.get("role") == "business_owner" and request.session.get("user_id") == user_id:
        return

    raise HTTPException(
        status_code=403,
        detail="Not authorized for this business",
    )


async def enforce_tenant_access_for_customer(request: Request, customer_phone: str) -> None:
    """
    Same rule as enforce_tenant_access(), for the many customer-detail
    routes (crm/lead/activity/timeline/opportunities in api/customer.py)
    that are keyed by customer_phone instead of user_id. Resolves which
    business that customer_phone belongs to first (a single query - see
    crm.customer_mapping.get_owning_business_user_id()), then applies the
    same rule. A customer_phone that doesn't resolve to any business -
    unknown number, or a business this session doesn't own - is treated
    as not authorized, same as a mismatched user_id.

    `async` (unlike enforce_tenant_access(), which is pure session
    lookups with no I/O) because this one runs a real DB query - routing
    it through run_in_threadpool keeps that off the event loop,
    consistent with every other blocking DB call in this codebase.
    """

    from fastapi.concurrency import run_in_threadpool
    from crm.customer_mapping import get_owning_business_user_id

    owning_user_id = await run_in_threadpool(
        get_owning_business_user_id, customer_phone
    )

    enforce_tenant_access(request, owning_user_id)


async def resolve_dashboard_user_id(request: Request):
    """
    Which business's user_id the dashboard/analytics/settings pages
    should render for the current session - always the logged-in
    business owner's own business, from the session set at login. Never
    client-influenced, no DB lookup needed.
    """

    if request.session.get("role") == "business_owner":
        return request.session.get("user_id")

    return None
