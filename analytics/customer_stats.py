"""
Per-customer / per-conversation stats: counts, unread, last message, lead
snapshot, and conversation history. Split out of analytics/analytics.py,
which had grown to mix several unrelated dashboard concerns in one file.
"""

from datetime import datetime

from crm.lead_manager import get_lead
from ai.sales_coach import get_next_best_action
from crm.customer_mapping import (
    get_business_phone_by_user,
    get_business_id,
    get_customer_name,
)
from database.db import get_crm_connection, get_conversation_connection


def get_stats(user_id):

    business_phone = get_business_phone_by_user(user_id)

    if not business_phone:

        return {
            "customers": 0
        }
    conn = get_crm_connection()

    cursor = conn.execute(
        """
        SELECT COUNT(*)
        FROM customer_mapping
        WHERE business_phone = ?
        """,
        (business_phone,)
    )

    customer_count = cursor.fetchone()[0]

    conn.close()

    return {
        "customers": customer_count
    }


def get_customer_stats(user_id):

    # business_id resolves through its own self-contained crm connection
    # (crm/customer_mapping.get_business_id()) - looked up before opening
    # the connection below so this function never holds a conversation-db
    # and a crm-db connection open at the same time (each is opened, used,
    # and closed in its own sequential block instead).
    business_id = get_business_id(user_id)

    if not business_id:
        return []

    conv_conn = get_conversation_connection()

    cursor = conv_conn.execute(
        """
        SELECT
            phone,
            COUNT(*) as message_count,
            MAX(created_at) as last_seen
        FROM conversations
        WHERE phone LIKE ?
        GROUP BY phone
        ORDER BY last_seen DESC
        """,
        (f"{business_id}:%",)
    )

    rows = cursor.fetchall()

    # Batch-fetch unread counts for all conversations in one query instead of
    # opening a new sqlite connection per customer (was an N+1 query pattern).
    unread_cursor = conv_conn.execute(
        """
        SELECT conversation_id, unread_count
        FROM unread_messages
        WHERE conversation_id LIKE ?
        """,
        (f"{business_id}:%",)
    )

    unread_by_conversation = {
        r[0]: r[1] for r in unread_cursor.fetchall()
    }

    # Batch-fetch each customer's single latest message in one query -
    # MAX(id) is used as "latest" (an autoincrement id only ever grows with
    # insert order, so it's equivalent to ORDER BY created_at DESC LIMIT 1
    # here but doesn't need a per-row subquery) instead of one query per
    # customer inside the loop below (was also an N+1 pattern). Done here,
    # still on conv_conn, before it's closed below - crm_conn (for the
    # name/lead lookups that follow) isn't opened until after that.
    last_message_cursor = conv_conn.execute(
        """
        SELECT c.phone, c.content
        FROM conversations c
        INNER JOIN (
            SELECT phone, MAX(id) as max_id
            FROM conversations
            WHERE phone LIKE ?
            GROUP BY phone
        ) latest
        ON c.phone = latest.phone AND c.id = latest.max_id
        """,
        (f"{business_id}:%",)
    )

    last_message_by_conversation = {
        r[0]: r[1] for r in last_message_cursor.fetchall()
    }

    conv_conn.close()

    # Batch-fetch customer names (auto-captured from WhatsApp ProfileName,
    # or manually set) for exactly the customers in this business, instead
    # of one query per customer.
    customer_phones = [
        (
            conv_id.split(":")[1]
            if ":" in conv_id
            else conv_id
        )
        for conv_id in (r[0] for r in rows)
    ]

    name_by_phone = {}
    lead_by_phone = {}

    if customer_phones:

        crm_conn = get_crm_connection()

        placeholders = ",".join("?" for _ in customer_phones)

        name_cursor = crm_conn.execute(
            f"""
            SELECT customer_phone, customer_name
            FROM customer_mapping
            WHERE customer_phone IN ({placeholders})
            """,
            customer_phones
        )

        name_by_phone = {
            r[0]: r[1] for r in name_cursor.fetchall()
        }

        # Batch-fetch lead info (score/status/intent/...) for every
        # customer in this business in one query, instead of one query per
        # customer inside the loop below (was an N+1 pattern - the
        # unread/name batching above already got this treatment, this one
        # slipped through).
        lead_cursor = crm_conn.execute(
            f"""
            SELECT
                customer_phone,
                lead_score,
                status,
                intent,
                buying_stage,
                sentiment,
                priority,
                confidence,
                ai_paused
            FROM leads
            WHERE customer_phone IN ({placeholders})
            """,
            customer_phones
        )

        lead_by_phone = {
            r[0]: r for r in lead_cursor.fetchall()
        }

        crm_conn.close()

    customers = []

    for row in rows:

        conversation_id = row[0]

        customer_phone = (
            conversation_id.split(":")[1]
            if ":" in conversation_id
            else conversation_id
        )

        unread_count = unread_by_conversation.get(conversation_id, 0)

        last_message = last_message_by_conversation.get(
            conversation_id, ""
        )

        lead_row = lead_by_phone.get(customer_phone)

        if lead_row:

            # lead_row columns: customer_phone, lead_score, status, intent,
            # buying_stage, sentiment, priority, confidence, ai_paused
            lead_score = lead_row[1]
            lead_status = lead_row[2]
            intent = lead_row[3]
            buying_stage = lead_row[4]
            sentiment = lead_row[5]
            priority = lead_row[6]
            confidence = lead_row[7]
            ai_paused = bool(lead_row[8])

        else:

            lead_score = 0
            lead_status = "New"
            intent = ""
            buying_stage = ""
            sentiment = ""
            priority = ""
            confidence = 0
            ai_paused = False

        try:

            last_seen_dt = datetime.strptime(
                row[2],
                "%Y-%m-%d %H:%M:%S"
            )

            last_seen_days = (
                datetime.now() - last_seen_dt
            ).days

        except (TypeError, ValueError):

            last_seen_days = 999

        customers.append({

            "phone": customer_phone,

            "name": name_by_phone.get(customer_phone),

            "message_count": row[1],

            "last_seen": row[2],

            "unread_count": unread_count,

            "last_message": last_message,

            "lead_score": lead_score,

            "status": lead_status,

            "intent": intent,

            "buying_stage": buying_stage,

            "sentiment": sentiment,

            "priority": priority,
            "last_seen_days": last_seen_days,

            "confidence": confidence,

            "ai_paused": ai_paused,

        })

    return customers


def search_customers(user_id, query):
    """
    Filter this business's customers by phone number, name, or message
    content - a customer matches if the query appears (case-insensitive)
    in their phone number, their name, or anywhere in their conversation
    history (not just the single most recent message shown in the list).
    """

    customers = get_customer_stats(user_id)

    if not query:
        return customers

    q = query.strip().lower()

    if not q:
        return customers

    # Cheap matches first: phone number and name, both already loaded.
    matched_phones = {
        c["phone"]
        for c in customers
        if q in c["phone"].lower()
        or q in (c["name"] or "").lower()
    }

    # Message-content match: search the actual conversation history, since
    # get_customer_stats() only carries each customer's single latest
    # message, not the full thread.
    business_id = get_business_id(user_id)

    if business_id:

        conn = get_conversation_connection()

        rows = conn.execute(
            """
            SELECT DISTINCT phone
            FROM conversations
            WHERE phone LIKE ?
            AND LOWER(content) LIKE ?
            """,
            (
                f"{business_id}:%",
                f"%{q}%"
            )
        ).fetchall()

        conn.close()

        for row in rows:

            conversation_id = row[0]

            customer_phone = (
                conversation_id.split(":")[1]
                if ":" in conversation_id
                else conversation_id
            )

            matched_phones.add(customer_phone)

    return [
        c for c in customers
        if c["phone"] in matched_phones
    ]


def get_conversation(
    user_id,
    customer_phone
):

    business_id = get_business_id(user_id)

    if not business_id:
        return []

    conversation_id = (
        f"{business_id}:{customer_phone}"
    )

    conn = get_conversation_connection()

    cursor = conn.execute(
        """
        SELECT role,
               content,
               created_at,
               sender
        FROM conversations
        WHERE phone = ?
        ORDER BY id
        """,
        (conversation_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        {
            "role": row[0],
            "content": row[1],
            "created_at": row[2],
            "sender": row[3]
        }
        for row in rows
    ]


def get_dashboard_metrics(user_id):
    """
    Single source of truth for the 4 header stat cards (Customers,
    Messages, Qualified Leads, Open Opportunities) on the dashboard.

    Previously this and templates/dashboard.html's loadCustomers() each
    computed customer/message counts independently from the same
    conversations rows - two DB round trips producing numbers that happen
    to agree today only because both used an identical (business_id:%)
    filter, but with no shared source of truth to guarantee that stays
    true. loadCustomers() has been trimmed back to only compute what only
    it can (qualified-lead count, from the customer list it already has to
    fetch to render the inbox); this function now owns customers/messages/
    open_opportunities so there's exactly one place each is computed.

    "today_messages" is kept even though no element on dashboard.html
    displays it (#todayMessages doesn't exist there) - ai/manager_assistant.py
    reads metrics['today_messages'] when answering "what are my metrics"
    style questions, so removing it would break that feature.

    "open_opportunities" is new: the header's 💰 stat used to be
    customers.filter(lead_score >= 60).length, a heuristic that has
    nothing to do with the actual opportunities table (the same one the
    Opportunity Pipeline chart and per-customer Opportunity Pipeline card
    read from) - it could over- or under-count real tracked opportunities
    depending on where lead scores happen to land. This counts real open
    rows from that table instead, so the header number matches what
    "Opportunities" means everywhere else in the app.
    """

    business_id = get_business_id(user_id)

    if not business_id:
        return {
            "customers": 0,
            "messages": 0,
            "today_messages": 0,
            "open_opportunities": 0
        }

    conv_conn = get_conversation_connection()

    customer_rows = conv_conn.execute(
        """
        SELECT DISTINCT phone
        FROM conversations
        WHERE phone LIKE ?
        """,
        (f"{business_id}:%",)
    ).fetchall()

    message_count = conv_conn.execute(
        """
        SELECT COUNT(*)
        FROM conversations
        WHERE phone LIKE ?
        """,
        (f"{business_id}:%",)
    ).fetchone()[0]

    today_count = conv_conn.execute(
        """
        SELECT COUNT(*)
        FROM conversations
        WHERE phone LIKE ?
        AND DATE(created_at) = CURRENT_DATE
        """,
        (f"{business_id}:%",)
    ).fetchone()[0]

    conv_conn.close()

    customer_phones = [
        row[0].split(":")[1] if ":" in row[0] else row[0]
        for row in customer_rows
    ]

    open_opportunities = 0

    if customer_phones:

        crm_conn = get_crm_connection()

        placeholders = ",".join("?" for _ in customer_phones)

        open_opportunities = crm_conn.execute(
            f"""
            SELECT COUNT(*)
            FROM opportunities
            WHERE status = 'Open'
            AND customer_phone IN ({placeholders})
            """,
            customer_phones
        ).fetchone()[0]

        crm_conn.close()

    return {
        "customers": len(customer_phones),
        "messages": message_count,
        "today_messages": today_count,
        "open_opportunities": open_opportunities
    }


def get_customer_profile(user_id, customer_phone):

    # Resolved before opening the conversation connection below, for two
    # reasons: it means this function never holds a conversation-db and a
    # crm-db connection open at once (get_business_id() opens/closes its
    # own crm connection internally), and it fixes a connection leak this
    # used to have - the early return below previously ran before `conn`
    # was ever opened, but used to sit *after* conn = get_conversation_connection(),
    # so a business_id lookup miss leaked a pooled connection every time.
    business_id = get_business_id(user_id)

    if not business_id:
        return {}

    conn = get_conversation_connection()

    cursor = conn.execute(
        """
        SELECT
            MIN(created_at),
            MAX(created_at),
            COUNT(*)
        FROM conversations
        WHERE phone = ?
        """,
        (f"{business_id}:{customer_phone}",)
    )

    row = cursor.fetchone()

    conn.close()

    lead = get_lead(customer_phone)

    profile = {
        "customer_phone": customer_phone,
        "name": get_customer_name(customer_phone),
        "first_seen": row[0],
        "last_seen": row[1],
        "message_count": row[2]
    }

    # Merge all lead intelligence automatically
    profile.update(lead)
    profile["next_best_action"] = get_next_best_action(lead)
    return profile


def get_top_customers(
    user_id,
    limit=5
):

    business_id = get_business_id(user_id)

    if not business_id:
        return []
    conn = get_conversation_connection()

    cursor = conn.execute(
        """
        SELECT
            phone,
            COUNT(*) as message_count
        FROM conversations
        WHERE phone LIKE ?
        GROUP BY phone
        ORDER BY message_count DESC
        LIMIT ?
        """,
        (
            f"{business_id}:%",
            limit
        )
    )

    rows = cursor.fetchall()

    conn.close()

    customers = []

    for row in rows:

        conversation_id = row[0]

        customer_phone = (
            conversation_id.split(":")[1]
            if ":" in conversation_id
            else conversation_id
        )

        customers.append({
            "phone": customer_phone,
            "message_count": row[1]
        })

    return customers
