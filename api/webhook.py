from fastapi import (
    APIRouter,
    Request,
    Form,
    HTTPException,
)
from fastapi.concurrency import run_in_threadpool
from config import (
    DEBUG,
    TWILIO_AUTH_TOKEN,
    BUSINESS_ID,
    LOAD_TEST_MODE,
)
import logging
logger = logging.getLogger(__name__)
from twilio.request_validator import RequestValidator
validator = RequestValidator(TWILIO_AUTH_TOKEN)

from crm.customer_mapping import (
    save_mapping,
    get_customer_by_number,
    get_business_id
)

from crm.lead_manager import get_lead, pause_ai
from ai.handoff import detect_explicit_handoff_request, is_negative_complaint

from conversations import (
    get_history,
    add_message,
    clear_history,
)

from unread_manager import increment_unread

from rag_handler import handle_rag

from whatsapp import send_message

from ai.lead_intelligence import refresh_customer_intelligence

from reminder_manager import (
    reminder_exists,
    upsert_reminder,
    close_reengagement_reminders,
)

from crm.activity_manager import add_activity
from fastapi import APIRouter
router = APIRouter()

@router.post("/webhook")
async def receive_message(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
    # The sender's WhatsApp display name. Twilio includes this on WhatsApp
    # messages when the sender has one set; not every message has it, so
    # it's optional. Used as a best-effort auto-captured customer name -
    # see save_mapping()/get_customer_stats() for how it's stored/read.
    ProfileName: str = Form(None)
):
    signature = request.headers.get("X-Twilio-Signature")

    # Twilio's signature is an HMAC over the webhook URL plus EVERY form
    # field it posted (To, MessageSid, AccountSid, ProfileName, WaId,
    # NumMedia, etc. - not just From/Body). Validating against a
    # hand-picked subset of fields recomputes a different signature than
    # Twilio sent, so validate() would fail for every real request - only
    # ever worked before because DEBUG skipped this branch entirely.
    # request.form() is safe to call again here even though the Form(...)
    # params above already triggered a parse - Starlette caches the
    # parsed body on the request instead of re-reading the stream.
    form = await request.form()
    form_data = dict(form)

    # -----------------------------
    # Validate Twilio
    # -----------------------------
    if DEBUG:
        logger.warning("⚠ DEBUG MODE - Twilio validation skipped")
        is_valid = True
    else:
        is_valid = validator.validate(
            str(request.url).replace(
                "http://",
                "https://"
            ),
            form_data,
            signature
        )

    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid Twilio Signature"
        )

    if not From.startswith("whatsapp:"):
        raise HTTPException(
            status_code=400,
            detail="Only WhatsApp supported"
        )

    try:

        from_number = From.replace("whatsapp:", "")
        to_number = To.replace("whatsapp:", "")
        user_text = Body.strip()

        # -----------------------------
        # Save mapping
        # -----------------------------
        await run_in_threadpool(
            save_mapping,
            customer_phone=from_number,
            business_phone=to_number,
            customer_name=(
                ProfileName.strip() if ProfileName else None
            )
        )

        business_user_id = await run_in_threadpool(
            get_customer_by_number,
            to_number
        )
        business_id = await run_in_threadpool(
            get_business_id,
            business_user_id
        )
        if not business_user_id:

            await send_message(
                from_number,
                "This business is not configured yet."
            )

            return {
                "status": "success"
            }

        # This deployment only ever handles its own business - normally
        # guaranteed by Twilio only calling this webhook for the WhatsApp
        # number configured on this business's Twilio account, but
        # checked explicitly rather than assumed, in case a number is
        # ever misconfigured to point at the wrong deployment. Silently
        # drops the message (no error response) rather than acting on
        # another business's data.
        if business_id != BUSINESS_ID:
            logger.error(
                "Webhook received for business_id=%s but this deployment "
                "is configured for BUSINESS_ID=%s - ignoring.",
                business_id, BUSINESS_ID
            )
            return {
                "status": "success"
            }

        logger.info(
            f"Incoming customer={from_number} "
            f"business={to_number}"
        )

        # -----------------------------
        # Reset command
        # -----------------------------
        if user_text.lower() == "reset":

            await run_in_threadpool(
                clear_history,
                f"{business_id}:{from_number}"
            )

            await send_message(
                from_number,
                "✅ Conversation history cleared."
            )

            return {
                "status": "success"
            }

        conversation_id = (
            f"{business_id}:{from_number}"
        )

        history = await run_in_threadpool(
            get_history,
            conversation_id
        )

        # -----------------------------
        # Save user message
        # -----------------------------
        await run_in_threadpool(
            add_message,
            conversation_id,
            "user",
            user_text
        )

        await run_in_threadpool(
            increment_unread,
            conversation_id
        )

        # This customer just messaged in on their own - auto-close any
        # open "gone quiet" reminder for them (see
        # reminder_manager.close_reengagement_reminders()'s docstring for
        # exactly which reminders qualify). Never allowed to block or
        # fail the actual message handling below it.
        try:
            await run_in_threadpool(
                close_reengagement_reminders,
                from_number
            )
        except Exception:
            logger.warning(
                "close_reengagement_reminders() failed for %s - "
                "continuing message handling regardless.",
                from_number,
                exc_info=True
            )

        # -----------------------------
        # Human Handoff - already paused
        # -----------------------------
        # See crm/lead_manager.py's pause_ai()/resume_ai() and
        # ai/handoff.py. Once a conversation is paused the AI stops
        # replying entirely (no reply generated, nothing sent) until a
        # team member resumes it from the dashboard - the message above
        # is still saved and counted unread so it shows up in the inbox
        # for a human to handle.
        existing_lead = await run_in_threadpool(get_lead, from_number)

        if existing_lead.get("ai_paused"):

            await run_in_threadpool(
                add_activity,
                from_number,
                "Handoff",
                "Message received while AI paused",
                user_text
            )

            logger.info(
                f"AI paused for {from_number} - skipping auto-reply"
            )

            return {
                "status": "success"
            }

        # -----------------------------
        # Human Handoff - explicit request
        # -----------------------------
        # Checked on the raw incoming text before generating any AI reply,
        # so an explicit "let me talk to a person" gets a short handoff
        # acknowledgment instead of an unrelated AI answer bolted onto it.
        handoff_phrase = detect_explicit_handoff_request(user_text)

        if handoff_phrase:

            await run_in_threadpool(
                pause_ai,
                from_number,
                f'Customer asked for a human ("{handoff_phrase}")'
            )

            handoff_reply = (
                "Got it - I'm connecting you with a member of our team "
                "who will follow up with you shortly."
            )

            await run_in_threadpool(
                add_message,
                conversation_id,
                "assistant",
                handoff_reply
            )

            await run_in_threadpool(
                add_activity,
                from_number,
                "Handoff",
                "AI paused - customer asked for a human",
                f'Trigger phrase: "{handoff_phrase}"'
            )

            await send_message(
                from_number,
                handoff_reply
            )

            return {
                "status": "success"
            }

        # -----------------------------
        # Generate AI Reply
        # -----------------------------
        reply = await handle_rag(
            user_text,
            history,
            user_id=business_user_id
        )

        # -----------------------------
        # Save assistant reply
        # -----------------------------
        await run_in_threadpool(
            add_message,
            conversation_id,
            "assistant",
            reply
        )

        # -----------------------------
        # Refresh CRM Intelligence
        # -----------------------------
        try:

            # NOTE: this is an `async def` function - it was previously
            # called without `await`, which meant `analysis` was actually
            # an unawaited coroutine object. `analysis.get(...)` below would
            # then raise AttributeError, get swallowed by the `except`
            # below, and get logged as "Lead Intelligence failed" - meaning
            # this entire block silently never ran for real incoming
            # WhatsApp messages (it did work correctly from api/ai.py and
            # api/chat.py, which already awaited it properly).
            analysis = await refresh_customer_intelligence(
                business_user_id,
                from_number
            )

            logger.info(
                f"Lead Intelligence: {analysis}"
            )

            # -----------------------------
            # Human Handoff - negative complaint
            # -----------------------------
            # This message's reply has already been generated above and
            # still gets sent below - it's a real answer to what the
            # customer just asked. The pause only takes effect for their
            # *next* message onward. Sentiment alone is too noisy to pause
            # on by itself (see ai/handoff.py's is_negative_complaint
            # docstring) - this requires Negative sentiment AND Complaint
            # intent together.
            if is_negative_complaint(analysis):

                await run_in_threadpool(
                    pause_ai,
                    from_number,
                    "Negative sentiment + complaint detected: "
                    + analysis.get("summary", "")[:200]
                )

                await run_in_threadpool(
                    add_activity,
                    from_number,
                    "Handoff",
                    "AI paused - complaint detected",
                    analysis.get("summary", "")
                )

            next_action = analysis.get(
                "next_action",
                "Follow up"
            )

            follow_up_days = analysis.get(
                "follow_up_days",
                1
            )

            priority = analysis.get(
                "priority",
                "Medium"
            )

            if not await run_in_threadpool(reminder_exists, from_number):

                await run_in_threadpool(
                    upsert_reminder,
                    from_number,
                    f"[{priority}] {next_action}",
                    follow_up_days
                )
                await run_in_threadpool(
                    add_activity,
                    from_number,

                    "Reminder",

                    "Follow-up Scheduled",

                    # No leading/trailing blank lines or indentation - the
                    # Customer Timeline renders this with
                    # white-space:pre-wrap, so stray blank lines/spaces
                    # here would show up as real empty space in the card.
                    f"{next_action}\n"
                    f"After {follow_up_days} day(s)\n"
                    f"Priority : {priority}"
                )

        except Exception as e:

            logger.exception(
                f"Lead Intelligence failed: {e}"
            )

        # -----------------------------
        # Send WhatsApp Reply
        # -----------------------------
        try:
            if LOAD_TEST_MODE:
                # See config.py's LOAD_TEST_MODE docstring - skips the
                # real Twilio API call so load-test runs measure this
                # app's own latency, not Twilio's, and don't spam
                # synthetic numbers through the real account.
                logger.info(
                    "LOAD_TEST_MODE - skipping real send to %s", from_number
                )
            else:
                await send_message(
                    from_number,
                    reply
                )
        except Exception as e:
            # The reply was already saved to conversation history and fed
            # into refresh_customer_intelligence() above, so without this
            # the rest of the pipeline behaves as if the customer actually
            # received it. A Twilio-side delivery failure (bad number,
            # opted out, rate limited, etc.) would otherwise leave zero
            # visible trace - surface it as a distinct log line plus a
            # Customer Timeline entry so a team member notices and can
            # follow up manually.
            logger.exception(
                f"Failed to deliver reply to {from_number}: {e}"
            )

            await run_in_threadpool(
                add_activity,
                from_number,
                "Delivery",
                "Failed to send AI reply",
                str(e)[:500]
            )

            return {
                "status": "error",
                "message": f"Reply generated but delivery failed: {e}"
            }

        return {
            "status": "success"
        }

    except Exception as e:

        logger.exception(
            f"Webhook error: {e}"
        )

        return {
            "status": "error",
            "message": str(e)
        }
