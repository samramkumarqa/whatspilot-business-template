from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
import logging

from conversations import (
    add_message,
    clear_history,
    get_history,
)

from rag_handler import handle_rag

from ai.lead_intelligence import (
    refresh_customer_intelligence,
)

router = APIRouter()

logger = logging.getLogger(__name__)


@router.post("/chat")
async def local_chat(
    phone: str,
    message: str
):

    try:

        logger.info(
            f"Local Chat: {phone}"
        )

        # Save user message
        await run_in_threadpool(
            add_message,
            phone,
            "user",
            message
        )

        # Load updated conversation
        history = await run_in_threadpool(get_history, phone)

        # Generate AI reply
        reply = await handle_rag(
            message,
            history,
            user_id=phone
        )

        # Save assistant reply
        await run_in_threadpool(
            add_message,
            phone,
            "assistant",
            reply
        )

        analysis = None

        try:

            analysis = await refresh_customer_intelligence(
                user_id=phone,
                customer_phone=phone
            )

            logger.info(
                f"Lead Intelligence: {analysis}"
            )

        except Exception as e:

            logger.exception(
                f"Lead Intelligence failed: {e}"
            )

        return {
            "status": "success",
            "reply": reply,
            "analysis": analysis
        }

    except Exception as e:

        logger.exception(
            f"Local chat error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }
    
@router.post("/reset/{phone}")
async def reset_chat(phone: str):

    logger.info(
        f"Conversation reset: {phone}"
    )

    await run_in_threadpool(clear_history, phone)

    return {
        "status": "success",
        "message": f"History cleared for {phone}"
    }
