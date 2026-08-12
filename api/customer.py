from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from auth import enforce_tenant_access, enforce_tenant_access_for_customer
from analytics.analytics import (
    get_customer_stats,
    search_customers,
    get_conversation,
    get_customer_profile,
    get_top_customers,
)

from crm.lead_manager import (
    get_lead,
    get_lead_timeline,
    update_lead,
    resume_ai,
    pause_ai,
)

from crm.opportunity_manager import (
    get_opportunities,
)

from crm.activity_manager import (
    get_activity,
    get_activity_timeline,
    add_activity,
)

from timeline_manager import get_customer_timeline
from crm.customer_mapping import get_business_id, set_customer_name
from unread_manager import clear_unread
from conversations import add_message
from whatsapp import send_message

router = APIRouter()

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Mirrors the client-side rules in templates/dashboard.html
# (sanitizeFreeTextInput/sanitizeNameInput/validate*()) - enforced here too
# since these routes can be called directly, bypassing the UI.
class LeadRequest(BaseModel):
    customer_phone: str

    # Matches the fixed set of options in the Status <select> - anything
    # else is rejected rather than silently stored.
    status: Literal[
        "New", "Interested", "Qualified",
        "Proposal Sent", "Closed Won", "Closed Lost"
    ]

    # Free text (full sentences) - only angle brackets are disallowed, as
    # a light markup-injection guard.
    notes: str = Field(default="", max_length=1000, pattern=r"^[^<>]*$")

class CustomerNameRequest(BaseModel):
    customer_phone: str

    # Letters, numbers, spaces, and common name punctuation (& - ' . ,) -
    # empty is allowed (clears the name back to showing the phone number).
    name: str = Field(
        default="", max_length=100,
        pattern=r"^[a-zA-Z0-9À-ÿ &'\-.,]*$"
    )


class ManualReplyRequest(BaseModel):

    # No angle-bracket restriction here unlike LeadRequest/CustomerNameRequest
    # above - this is real chat content sent to a WhatsApp customer, not
    # structured CRM data, and the dashboard already safely HTML-escapes
    # it before rendering (see renderMarkdownBody() in dashboard.html,
    # same escaping AI replies go through). 4096 matches WhatsApp's own
    # text message length limit.
    message: str = Field(min_length=1, max_length=4096)

    @field_validator("message")
    @classmethod
    def require_non_blank_message(cls, value):

        stripped = value.strip()

        if not stripped:
            raise ValueError("Message cannot be empty.")

        return stripped


@router.get("/customer-details/{user_id}")
async def customer_details(
    user_id: str,
    request: Request
):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "customers": await run_in_threadpool(
            get_customer_stats,
            user_id
        )
    }

@router.get("/customer-search/{user_id}")
async def customer_search(
    user_id: str,
    request: Request,
    q: str = ""
):

    enforce_tenant_access(request, user_id)

    # Matches phone number, customer name, or message content anywhere in
    # the conversation history - see analytics/customer_stats.py.
    customers = await run_in_threadpool(
        search_customers,
        user_id,
        q
    )

    return {
        "status": "success",
        "customers": customers
    }

@router.get(
    "/conversation/{user_id}/{customer_phone}"
)
async def conversation_view(
    user_id: str,
    customer_phone: str,
    request: Request
):

    enforce_tenant_access(request, user_id)

    business_id = await run_in_threadpool(get_business_id, user_id)

    conversation_id = (
        f"{business_id}:{customer_phone}"
    )

    await run_in_threadpool(clear_unread, conversation_id)

    return {
        "status": "success",
        "messages": await run_in_threadpool(
            get_conversation,
            user_id,
            customer_phone
        )
    }


@router.post("/conversation/{user_id}/{customer_phone}/reply")
async def send_manual_reply(
    user_id: str,
    customer_phone: str,
    request: ManualReplyRequest,
    http_request: Request
):
    """
    Sends a real WhatsApp message on the business's behalf from the
    dashboard's reply box - the "close the loop" complement to human
    handoff (see crm/lead_manager.py's pause_ai() and ai/handoff.py).

    The message is sent via Twilio first, and only saved/logged/paused
    afterward - if the send itself fails (bad number, outside the 24h
    session window without an approved template, Twilio error), nothing
    gets written, so the transcript never shows a message that was never
    actually delivered.

    Sending a manual reply always (re)pauses the AI for this customer
    afterward, even if it wasn't already paused - once a team member has
    stepped in, the bot shouldn't jump back in and answer the customer's
    next message on top of what a human just said. A team member resumes
    the AI explicitly via the Customer Info panel's "Resume AI" button
    when they're done.
    """

    enforce_tenant_access(http_request, user_id)

    business_id = await run_in_threadpool(get_business_id, user_id)

    conversation_id = f"{business_id}:{customer_phone}"

    await send_message(customer_phone, request.message)

    await run_in_threadpool(
        add_message,
        conversation_id,
        "assistant",
        request.message,
        "Manual"
    )

    await run_in_threadpool(
        pause_ai,
        customer_phone,
        "Team member sent a manual reply"
    )

    await run_in_threadpool(
        add_activity,
        customer_phone,
        "Manual",
        "Manual reply sent",
        request.message
    )

    return {
        "status": "success"
    }


@router.get("/lead/{customer_phone}")
async def lead_details(
    customer_phone: str,
    request: Request
):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "lead": await run_in_threadpool(
            get_lead,
            customer_phone
        )
    }


@router.get("/customer-profile/{user_id}/{customer_phone}")
async def customer_profile(user_id: str, customer_phone: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "profile": await run_in_threadpool(
            get_customer_profile,
            user_id,
            customer_phone
        )
    }

@router.post("/customer-name")
async def save_customer_name(request: CustomerNameRequest, http_request: Request):

    await enforce_tenant_access_for_customer(http_request, request.customer_phone)

    name = request.name.strip()

    await run_in_threadpool(
        set_customer_name,
        request.customer_phone,
        name if name else None
    )

    return {
        "status": "success",
        "name": name
    }

@router.post("/lead")
async def save_lead(request: LeadRequest, http_request: Request):

    await enforce_tenant_access_for_customer(http_request, request.customer_phone)

    current_lead = await run_in_threadpool(get_lead, request.customer_phone)

    await run_in_threadpool(
        update_lead,
        customer_phone=request.customer_phone,
        status=request.status,
        notes=request.notes,
        confidence=current_lead.get("confidence", 50),
        reason="Updated manually",
        updated_by="Manual"
    )

    await run_in_threadpool(
        add_activity,
        request.customer_phone,

        "Manual",

        "Lead Updated Manually",

        # No leading/trailing blank lines or indentation - the Customer
        # Timeline renders this with white-space:pre-wrap, so stray blank
        # lines/spaces here would show up as real empty space in the card.
        f"Status : {request.status}\n"
        f"Notes : {request.notes}"
    )

    return {
        "status": "success",
        "message": "Lead updated successfully",
        "lead": await run_in_threadpool(get_lead, request.customer_phone)
    }

@router.post("/lead/{customer_phone}/resume-ai")
async def resume_ai_route(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    # See crm/lead_manager.py's pause_ai()/resume_ai() and
    # ai/handoff.py - called from the Customer Info panel's "Resume AI"
    # button once a team member has picked up a handed-off conversation.
    await run_in_threadpool(resume_ai, customer_phone)

    return {
        "status": "success"
    }


@router.get("/lead-timeline/{customer_phone}")
async def lead_timeline(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "timeline": await run_in_threadpool(get_lead_timeline, customer_phone)
    }


@router.get("/opportunities/{customer_phone}")
async def opportunities(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "opportunities": await run_in_threadpool(get_opportunities, customer_phone)
    }

@router.get("/activity/{customer_phone}")

async def activity(customer_phone, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {

        "status":"success",

        "activity": await run_in_threadpool(get_activity, customer_phone)
    }

@router.get("/customer-timeline/{customer_phone}")
async def customer_timeline(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "timeline": await run_in_threadpool(
            get_customer_timeline,
            customer_phone
        )
    }

@router.get("/activity-timeline/{customer_phone}")
async def activity_timeline(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "timeline": await run_in_threadpool(get_activity_timeline, customer_phone)
    }

# NOTE: this file previously also defined GET /timeline/{customer_phone}
# (customer_timeline_3) here - an exact duplicate of GET
# /customer-timeline/{customer_phone} above, both calling the same
# get_customer_timeline(). Nothing in the frontend called /timeline, so it
# was removed rather than kept as a second name for the same endpoint.