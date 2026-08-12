import logging

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from config import BUSINESS_ID
from crm.customer_mapping import get_business_by_login_number
from rate_limit import is_rate_limited, record_attempt
from verify import VerifyNotConfigured, check_otp, send_otp

logger = logging.getLogger(__name__)

router = APIRouter()

templates = Jinja2Templates(directory="templates")


# ==========================================================
# Business-owner login (WhatsApp/SMS OTP via Twilio Verify)
# ==========================================================
# Two-step PRG flow: 1) GET/POST /business-login - owner enters their
# phone number, 2) GET/POST /business-login/verify - owner enters the
# code they got.
#
# The phone number being verified lives in request.session (not a
# hidden form field) between steps 1 and 2, so step 2 can't be reached
# with an arbitrary phone number that was never actually sent a code.
#
# This deployment serves exactly one business (see config.py's
# BUSINESS_ID - set per customer at provisioning time). The shared
# Postgres database still has every business's row in it, so
# get_business_by_login_number() alone would happily log in *any*
# business's owner into *this* customer's portal if they had the phone
# number for a different, unrelated business. The BUSINESS_ID check
# below is what actually confines this deployment to its own customer.


def _business_matches_this_deployment(business) -> bool:
    if not BUSINESS_ID:
        # Fails closed rather than open - an unconfigured BUSINESS_ID
        # would otherwise silently allow any business in the shared
        # database to log into this deployment.
        logger.error("BUSINESS_ID is not configured for this deployment")
        return False
    return business.get("business_id") == BUSINESS_ID


@router.get("/business-login")
async def business_login_page(request: Request):

    return templates.TemplateResponse(
        request=request,
        name="business_login.html",
        context={
            "error": request.query_params.get("error"),
        }
    )


@router.post("/business-login")
async def business_login_submit(request: Request):

    form = await request.form()

    phone = (form.get("phone") or "").strip()

    if not phone.startswith("+"):
        return RedirectResponse(
            url="/business-login?error=format",
            status_code=303
        )

    # Keyed by phone (not IP) - the thing worth limiting here is how many
    # OTP SMS messages a given number can be sent, since that's real cost
    # and a spam vector regardless of which IP is requesting it. 3 sends
    # / 10 minutes is well above what a real owner needs (one send, maybe
    # a resend if it didn't arrive) but stops a number from being
    # hammered with codes.
    rate_key = f"otp_send:{phone}"

    if is_rate_limited(rate_key, max_attempts=3, window_seconds=600):
        return RedirectResponse(
            url="/business-login?error=ratelimited",
            status_code=303
        )

    record_attempt(rate_key)

    business = await run_in_threadpool(get_business_by_login_number, phone)

    if not business or not _business_matches_this_deployment(business):
        # Deliberately vague - doesn't reveal whether this number
        # belongs to an inactive/unregistered business, a different
        # customer's business, or a typo.
        return RedirectResponse(
            url="/business-login?error=notfound",
            status_code=303
        )

    try:
        await run_in_threadpool(send_otp, phone)
    except VerifyNotConfigured:
        logger.error("Business login attempted but Verify isn't configured")
        return RedirectResponse(
            url="/business-login?error=unavailable",
            status_code=303
        )
    except Exception:
        logger.exception("Failed to send OTP to %s", phone)
        return RedirectResponse(
            url="/business-login?error=send_failed",
            status_code=303
        )

    request.session["otp_pending_phone"] = phone
    request.session["otp_pending_user_id"] = business["user_id"]

    return RedirectResponse(url="/business-login/verify", status_code=303)


@router.get("/business-login/verify")
async def business_login_verify_page(request: Request):

    if not request.session.get("otp_pending_phone"):
        return RedirectResponse(url="/business-login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="business_login_verify.html",
        context={
            "phone": request.session["otp_pending_phone"],
            "error": request.query_params.get("error"),
        }
    )


@router.post("/business-login/verify")
async def business_login_verify_submit(request: Request):

    phone = request.session.get("otp_pending_phone")
    user_id = request.session.get("otp_pending_user_id")

    if not phone or not user_id:
        return RedirectResponse(url="/business-login", status_code=303)

    # Defense in depth on top of Twilio Verify's own attempt limit/expiry
    # (see verify.py) - keyed by phone rather than session, since the
    # session's otp_pending_phone is exactly what's being guessed against
    # and a determined attacker could otherwise just start a fresh
    # session per batch of guesses.
    rate_key = f"otp_verify:{phone}"

    if is_rate_limited(rate_key, max_attempts=5, window_seconds=600):
        return RedirectResponse(
            url="/business-login/verify?error=ratelimited",
            status_code=303
        )

    record_attempt(rate_key)

    form = await request.form()
    code = (form.get("code") or "").strip()

    try:
        valid = await run_in_threadpool(check_otp, phone, code)
    except VerifyNotConfigured:
        logger.error("Business login verify attempted but Verify isn't configured")
        return RedirectResponse(
            url="/business-login?error=unavailable",
            status_code=303
        )

    if not valid:
        return RedirectResponse(
            url="/business-login/verify?error=1",
            status_code=303
        )

    # Re-check the business is still active and still belongs to this
    # deployment (rather than trusting the values stashed at step 1) -
    # covers the edge case of an admin deactivating this business in the
    # window between sending the code and it being verified.
    business = await run_in_threadpool(get_business_by_login_number, phone)

    if not business or not _business_matches_this_deployment(business):
        request.session.pop("otp_pending_phone", None)
        request.session.pop("otp_pending_user_id", None)
        return RedirectResponse(
            url="/business-login?error=notfound",
            status_code=303
        )

    request.session.pop("otp_pending_phone", None)
    request.session.pop("otp_pending_user_id", None)

    request.session["role"] = "business_owner"
    request.session["user_id"] = business["user_id"]
    request.session["business_id"] = business["business_id"]

    return RedirectResponse(url="/", status_code=303)
