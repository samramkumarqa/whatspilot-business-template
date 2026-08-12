from ai.lead_ai import calculate_lead_score
from database.db import get_crm_connection


# Terminal pipeline states - once a deal is here, an automated update
# (AI-driven, from every incoming message) should never silently move it
# back into an earlier stage. Only a manual edit should do that. Shared by
# auto_update_lead() and update_lead_intelligence().
LOCKED_STATUSES = [
    "Proposal Sent",
    "Closed Won",
    "Closed Lost"
]


DEFAULT_LEAD = {
    "customer_phone": "",
    "status": "New",
    "notes": "",
    "confidence": 0,
    "reason": "",
    "updated_by": "Manual",

    "lead_score": 0,
    "intent": "",
    "buying_stage": "",
    "sentiment": "",
    "objection": "",

    "probability": 0,
    "priority": "Medium",

    "next_action": "",
    "follow_up_days": 1,

    "summary": "",
    "ai_summary": "",

    "tags": "",

    "ai_paused": 0,
    "ai_paused_reason": "",
    "ai_paused_at": None
}

def init_leads():

    conn = get_crm_connection()

    # NOTE: this previously only defined
    # (customer_phone, status, notes, confidence, reason, updated_by) -
    # missing lead_score, intent, buying_stage, sentiment, objection,
    # probability, next_action, ai_summary, follow_up_days, tags, priority,
    # and summary, all of which the live production data/app.db actually has
    # (added via manual ALTER TABLE at some point, never reflected back into
    # this function) and which update_lead()/update_lead_intelligence() in
    # this same file write to unconditionally. A fresh copy of this database
    # would fail immediately on the first update_lead() call with
    # "table leads has no column named lead_score". Schema below now matches
    # the real, live table.
    conn.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        customer_phone TEXT PRIMARY KEY,
        status TEXT DEFAULT 'New',
        notes TEXT DEFAULT '',
        confidence INTEGER DEFAULT 50,
        reason TEXT DEFAULT '',
        updated_by TEXT DEFAULT 'Manual',
        lead_score INTEGER DEFAULT 0,
        intent TEXT DEFAULT '',
        buying_stage TEXT DEFAULT '',
        sentiment TEXT DEFAULT '',
        objection TEXT DEFAULT '',
        probability INTEGER DEFAULT 0,
        next_action TEXT DEFAULT '',
        ai_summary TEXT DEFAULT '',
        follow_up_days INTEGER DEFAULT 1,
        tags TEXT DEFAULT '',
        priority TEXT DEFAULT 'Medium',
        summary TEXT DEFAULT ''
    )
    """)

    # Human handoff: once a customer either explicitly asks for a person
    # or the AI detects a genuine complaint (Negative sentiment + Complaint
    # intent - see ai/handoff.py), ai_paused=1 stops api/webhook.py from
    # auto-replying to that customer's future messages until a human
    # resumes AI from the dashboard (see pause_ai()/resume_ai() below).
    existing_lead_columns = {
        row[0] for row in
        conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'leads'"
        ).fetchall()
    }

    if "ai_paused" not in existing_lead_columns:
        conn.execute(
            "ALTER TABLE leads ADD COLUMN ai_paused INTEGER DEFAULT 0"
        )

    if "ai_paused_reason" not in existing_lead_columns:
        conn.execute(
            "ALTER TABLE leads ADD COLUMN ai_paused_reason TEXT DEFAULT ''"
        )

    if "ai_paused_at" not in existing_lead_columns:
        conn.execute(
            "ALTER TABLE leads ADD COLUMN ai_paused_at TIMESTAMP"
        )

    # NOTE: also kept in sync with crm/opportunity_manager.py's
    # init_opportunities(), which creates the same table - see the note
    # there. init_leads() runs first in main.py, so this definition is the
    # one that actually applies on a fresh database.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opportunities (

            id SERIAL PRIMARY KEY,

            customer_phone TEXT,

            opportunity_type TEXT,

            confidence INTEGER,

            reason TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Open',
            updated_at TIMESTAMP,
            estimated_value INTEGER DEFAULT 0
        )
        """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS lead_history (
        id SERIAL PRIMARY KEY,
        customer_phone TEXT,
        status TEXT,
        confidence INTEGER,
        reason TEXT,
        updated_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_opportunities_customer_phone "
        "ON opportunities(customer_phone)"
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lead_history_customer_phone "
        "ON lead_history(customer_phone)"
    )

    conn.commit()
    conn.close()

def get_lead(customer_phone):

    conn = get_crm_connection()
    
    row = conn.execute(
        """
        SELECT *
        FROM leads
        WHERE customer_phone = ?
        """,
        (customer_phone,)
    ).fetchone()

    conn.close()

    if row:
        return dict(row)

    lead = DEFAULT_LEAD.copy()
    lead["customer_phone"] = customer_phone

    return lead


def pause_ai(customer_phone, reason):
    """
    Marks a customer's AI auto-replies as paused (human handoff) - see
    api/webhook.py, which checks ai_paused before calling handle_rag() for
    that customer's future incoming messages. Uses INSERT ... ON CONFLICT
    rather than a plain UPDATE so this still works for a customer with no
    existing leads row (e.g. their very first message is the one that
    triggers an explicit handoff request).
    """

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO leads (customer_phone, ai_paused, ai_paused_reason, ai_paused_at)
        VALUES (?, 1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(customer_phone) DO UPDATE SET
            ai_paused = 1,
            ai_paused_reason = excluded.ai_paused_reason,
            ai_paused_at = CURRENT_TIMESTAMP
        """,
        (customer_phone, reason)
    )

    conn.commit()
    conn.close()


def resume_ai(customer_phone):
    """
    Clears a human handoff pause, so api/webhook.py resumes auto-replying
    to this customer's messages. Called from the dashboard's Customer Info
    panel once a team member has handled the conversation.
    """

    conn = get_crm_connection()

    conn.execute(
        """
        UPDATE leads
        SET
            ai_paused = 0,
            ai_paused_reason = '',
            ai_paused_at = NULL
        WHERE customer_phone = ?
        """,
        (customer_phone,)
    )

    conn.commit()
    conn.close()


def update_lead(
    customer_phone,
    status,
    notes,
    confidence=0,
    reason="",
    updated_by="Manual"
):

    lead_score = calculate_lead_score(
        status,
        confidence
    )

    conn = get_crm_connection()

    # BUG FIX: this used to be "INSERT OR REPLACE INTO leads (...7 columns)".
    # INSERT OR REPLACE deletes the existing row and inserts a brand new one,
    # so every column NOT in that 7-column list (intent, buying_stage,
    # sentiment, objection, priority, probability, next_action,
    # follow_up_days, ai_summary, tags, summary) silently fell back to its
    # table DEFAULT every time this ran - i.e. every manual "Save Lead"
    # click (POST /lead in api/customer.py) wiped out all AI-derived lead
    # intelligence for that customer, even if the user only changed Status
    # or Notes. ON CONFLICT DO UPDATE only touches the columns listed in
    # SET, so the AI-derived fields survive a manual edit; a brand-new
    # customer_phone still gets the normal column DEFAULTs on first INSERT.
    conn.execute(
        """
        INSERT INTO leads
        (
            customer_phone,
            status,
            notes,
            confidence,
            reason,
            updated_by,
            lead_score
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(customer_phone) DO UPDATE SET
            status=excluded.status,
            notes=excluded.notes,
            confidence=excluded.confidence,
            reason=excluded.reason,
            updated_by=excluded.updated_by,
            lead_score=excluded.lead_score
        """,
        (
            customer_phone,
            status,
            notes,
            confidence,
            reason,
            updated_by,
            lead_score
        )
    )

    conn.execute(
        """
        INSERT INTO lead_history
        (
            customer_phone,
            status,
            confidence,
            reason,
            updated_by
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            customer_phone,
            status,
            confidence,
            reason,
            updated_by
        )
    )

    conn.commit()
    conn.close()

def get_lead_timeline(customer_phone):

    conn = get_crm_connection()

    cursor = conn.execute(
        """
        SELECT
            status,
            confidence,
            reason,
            updated_by,
            created_at
        FROM lead_history
        WHERE customer_phone = ?
        ORDER BY created_at DESC
        """,
        (customer_phone,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        {
            "status": row[0],
            "confidence": row[1],
            "reason": row[2],
            "updated_by": row[3],
            "created_at": row[4]
        }
        for row in rows
    ]

def get_lead_categories():

    conn = get_crm_connection()

    cursor = conn.execute("""
        SELECT
            customer_phone,
            status,
            lead_score
        FROM leads
    """)

    rows = cursor.fetchall()

    conn.close()

    hot = []
    warm = []
    cold = []

    for phone, status, score in rows:

        lead = {
            "customer_phone": phone,
            "status": status,
            "lead_score": score
        }

        if score >= 80:
            hot.append(lead)
        elif score >= 50:
            warm.append(lead)
        else:
            cold.append(lead)

    return {
        "hot": hot,
        "warm": warm,
        "cold": cold
    }

def save_opportunity(
    customer_phone,
    opportunity_type,
    confidence,
    reason
):

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO opportunities
        (
            customer_phone,
            opportunity_type,
            confidence,
            reason
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            customer_phone,
            opportunity_type,
            confidence,
            reason
        )
    )

    conn.commit()
    conn.close()

def update_lead_intelligence(
    customer_phone,
    analysis
):
    """
    Save AI Lead Intelligence into CRM.
    """

    # BUG FIX: this used to write analysis["buying_stage"] into the
    # "status" column (a column/value mismatch - buying_stage is a
    # different vocabulary: Awareness/Interested/Considering/Ready to
    # Buy/Customer, vs. status's New/Interested/Qualified/Proposal
    # Sent/Closed Won/Closed Lost). That meant "status" almost never held
    # a real pipeline status, so any automation condition on Lead Status
    # rarely matched. analysis["status"] (added to the same LLM call, see
    # ai/lead_intelligence.py's SYSTEM_PROMPT) is the real one.
    #
    # Also: once a deal is in a terminal/locked state (Proposal
    # Sent/Closed Won/Closed Lost), an automatic per-message update should
    # never silently move it backwards - only a manual edit should.
    current = get_lead(customer_phone)

    new_status = analysis["status"]

    if current["status"] in LOCKED_STATUSES:
        new_status = current["status"]

    conn = get_crm_connection()

    conn.execute(
        """
        INSERT INTO leads
        (
            customer_phone,
            status,
            confidence,
            reason,
            updated_by,
            lead_score,

            intent,
            buying_stage,
            sentiment,
            objection,
            priority,
            probability,
            next_action,
            follow_up_days,
            summary,
            tags
        )

        VALUES
        (
            ?,?,?,?,?,?,
            ?,?,?,?,?,?,
            ?,?,?,?
        )

        ON CONFLICT(customer_phone)
        DO UPDATE SET

            status=excluded.status,
            confidence=excluded.confidence,
            reason=excluded.reason,
            updated_by='AI',
            lead_score=excluded.lead_score,

            intent=excluded.intent,
            buying_stage=excluded.buying_stage,
            sentiment=excluded.sentiment,
            objection=excluded.objection,
            priority=excluded.priority,
            probability=excluded.probability,
            next_action=excluded.next_action,
            follow_up_days=excluded.follow_up_days,
            summary=excluded.summary,
            tags=excluded.tags
        """,
        (
            customer_phone,

            new_status,

            analysis["confidence"],

            analysis["summary"],

            "AI",

            analysis["lead_score"],

            analysis["intent"],

            analysis["buying_stage"],

            analysis["sentiment"],

            analysis["objection"],

            analysis["priority"],

            analysis["probability"],

            analysis["next_action"],

            analysis["follow_up_days"],

            analysis["summary"],

            ",".join(analysis["tags"])
        )
    )

    conn.execute(
        """
        INSERT INTO lead_history
        (
            customer_phone,
            status,
            confidence,
            reason,
            updated_by
        )

        VALUES
        (
            ?,?,?,?,?
        )
        """,
        (
            customer_phone,

            new_status,

            analysis["confidence"],

            analysis["summary"],

            "AI"
        )
    )

    conn.commit()

    conn.close()

def auto_update_lead(
    customer_phone,
    ai_status,
    confidence=0,
    reason=""
):

    current = get_lead(customer_phone)

    current_status = current["status"]

    if current_status in LOCKED_STATUSES:
        return

    update_lead(
        customer_phone,
        ai_status,
        current["notes"],
        confidence,
        reason,
        "AI"
    )