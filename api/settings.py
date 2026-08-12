from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from auth import enforce_tenant_access
from database.db import get_conversation_connection
from crm.customer_mapping import (
    save_business_settings,
    get_business_settings,
    save_customer_number,
    get_business_id,
    get_business_phone_by_user,
    get_customers,
)

from conversations import get_last_customer_update

router = APIRouter()

# Mirrors the client-side rules in templates/settings.html (sanitize*Input/
# validate*() there) - the server enforces the same limits independently
# since these routes can be called directly, bypassing any UI checks.
class BusinessSettingsRequest(
    BaseModel
):
    user_id: str = Field(
        min_length=7, max_length=16, pattern=r"^\+?[0-9]{7,15}$"
    )

    # Letters, numbers, spaces, and common business-name punctuation
    # (& - ' . ,) - same allowlist as the Business Name field's
    # sanitizeBusinessNameInput() on the settings page.
    business_name: str = Field(
        min_length=1, max_length=100,
        pattern=r"^[a-zA-Z0-9À-ÿ &'\-.,]+$"
    )

    # Free text (full sentences, punctuation, emoji all allowed) - only
    # angle brackets are disallowed, as a light markup-injection guard.
    welcome_message: str = Field(default="", max_length=300, pattern=r"^[^<>]*$")
    ai_instructions: str = Field(default="", max_length=1000, pattern=r"^[^<>]*$")

class CustomerNumberRequest(
    BaseModel
):
    user_id: str
    whatsapp_number: str
    business_id: str | None = None

@router.post("/business-settings")
async def save_settings(
    request: BusinessSettingsRequest,
    http_request: Request
):

    enforce_tenant_access(http_request, request.user_id)

    await run_in_threadpool(
        save_business_settings,
        request.user_id,
        request.business_name,
        request.welcome_message,
        request.ai_instructions
    )

    return {
        "status": "success"
    }
@router.get("/business-settings/{user_id}")
async def get_settings(
    user_id: str,
    request: Request
):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "settings": await run_in_threadpool(
            get_business_settings,
            user_id
        )
    }

@router.post("/customer-number")
async def save_number(
    request: CustomerNumberRequest,
    http_request: Request
):

    enforce_tenant_access(http_request, request.user_id)

    # BUG FIX: this used to hardcode "business_001" regardless of which
    # business was actually saving its number - harmless for the one
    # original business (whose business_id genuinely is business_001),
    # but would have silently mislabeled every other registered
    # business's customer_numbers row with the wrong business_id the
    # first time they confirmed their WhatsApp number from Settings.
    # Resolves the real business_id already assigned at registration
    # (see crm/customer_mapping.py's register_business()) instead.
    business_id = await run_in_threadpool(get_business_id, request.user_id)

    await run_in_threadpool(
        save_customer_number,
        request.user_id,
        request.whatsapp_number,
        business_id
    )

    return {
        "status": "success"
    }

@router.get("/customer-number/{user_id}")
async def get_number(
    user_id: str,
    request: Request
):

    enforce_tenant_access(request, user_id)

    number = await run_in_threadpool(
        get_business_phone_by_user,
        user_id
    )

    return {
    "status":"success",
    "configured": number is not None,
    "whatsapp_number": number
}


@router.get("/customers/{user_id}")
async def customers(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "customers": await run_in_threadpool(get_customers, user_id)
    }

@router.get("/customers-last/{user_id}")
async def customers_last(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
    "status": "success",
    "last_update": await run_in_threadpool(get_last_customer_update, user_id)
}

def _fetch_last_message(user_id: str, customer_phone: str):
    conn = get_conversation_connection()

    row = conn.execute(
        """
        SELECT MAX(created_at)
        FROM conversations
        WHERE phone=?
        """,
        (f"{user_id}:{customer_phone}",)
    ).fetchone()

    conn.close()

    return row[0] or ""

@router.get("/conversation-last/{user_id}/{customer_phone}")
async def conversation_last(user_id: str, customer_phone: str, request: Request):

    enforce_tenant_access(request, user_id)

    last_message = await run_in_threadpool(
        _fetch_last_message,
        user_id,
        customer_phone
    )

    return {
        "last_message": last_message
    }