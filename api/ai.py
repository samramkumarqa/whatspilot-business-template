from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from auth import enforce_tenant_access, enforce_tenant_access_for_customer
from ai.manager_assistant import ask_manager
from followup_ai import generate_followup

from analytics.analytics import get_conversation

from crm.lead_manager import get_lead

from crm.followup_manager import (
    save_followup,
    get_followups
)

from analytics.analytics import get_dashboard

router = APIRouter()

class ManagerQuestion(BaseModel):
    user_id: str
    question: str

@router.get("/generate-followup/{user_id}/{customer_phone}")
async def generate_followup_message(
    user_id: str,
    customer_phone: str,
    request: Request
):

    enforce_tenant_access(request, user_id)

    messages = await run_in_threadpool(
        get_conversation,
        user_id,
        customer_phone
    )

    conversation = ""

    for msg in messages:

        role = (
            "Customer"
            if msg["role"] == "user"
            else "Assistant"
        )

        conversation += (
            f"{role}: {msg['content']}\n"
        )

    lead = await run_in_threadpool(get_lead, customer_phone)

    followup = await run_in_threadpool(
        generate_followup,
        conversation,
        lead
    )
    await run_in_threadpool(
        save_followup,
        customer_phone,
        followup
    )

    return {
        "status": "success",
        "followup": followup
    }

@router.get("/followups/{customer_phone}")
async def followups(customer_phone: str, request: Request):

    await enforce_tenant_access_for_customer(request, customer_phone)

    return {
        "status": "success",
        "followups": await run_in_threadpool(get_followups, customer_phone)
    }


@router.get("/executive-dashboard/{user_id}")
async def executive_dashboard(user_id: str, request: Request):

    enforce_tenant_access(request, user_id)

    return {
        "status": "success",
        "dashboard": await run_in_threadpool(get_dashboard, user_id)
    }

@router.post("/manager-assistant")
def manager_assistant(question: ManagerQuestion, request: Request):

    enforce_tenant_access(request, question.user_id)

    answer = ask_manager(
        question.user_id,
        question.question
    )

    return {
        "question": question.question,
        "answer": answer
    }
