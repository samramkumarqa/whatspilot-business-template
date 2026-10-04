from datetime import timedelta

from database.db import get_crm_connection
from llm import ask_llm

# How long a cached executive summary stays valid before get_dashboard()
# (see analytics/analytics.py) regenerates it with a fresh LLM call.
#
# This endpoint is on the hot path of every dashboard page load/refresh -
# load testing (load_test_dashboard.py) measured /dashboard/{user_id} at
# ~1.4s mean latency vs 3-10ms for every other dashboard endpoint, almost
# entirely attributable to this function's single blocking Groq call
# (ask_llm() - see llm.py). A business's lead/pipeline/reminder numbers
# don't meaningfully change inside a 15-minute window, so there's no
# reason to pay that latency (and burn Groq quota) on every single
# refresh - caching keeps the page fast while still feeling "current"
# within a normal browsing session.
CACHE_TTL = timedelta(minutes=15)


def init_executive_summary_cache():
    """
    One row per business owner holding their most recently generated
    executive summary, so repeat dashboard loads within CACHE_TTL can
    skip the LLM call entirely. Stored in Postgres (not in-process
    memory) for the same reason every other piece of app state is -
    survives a worker restart/redeploy instead of silently reverting to
    "call the LLM on every request" until the cache warms back up.
    """

    conn = get_crm_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS executive_summary_cache (
            user_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def _get_cached_summary(user_id):
    conn = get_crm_connection()

    # The freshness check is done entirely in SQL (generated_at vs
    # Postgres's own NOW()) rather than pulling generated_at back into
    # Python and comparing against datetime.utcnow() - CURRENT_TIMESTAMP
    # written into a TIMESTAMP (no time zone) column reflects the
    # database server's own session time zone, not necessarily UTC, so
    # comparing it against a UTC-based Python clock silently drifts by
    # whatever that offset is. Keeping both sides of the comparison on
    # Postgres's own clock sidesteps that entirely.
    row = conn.execute(
        "SELECT summary FROM executive_summary_cache "
        "WHERE user_id = ? "
        "AND generated_at > NOW() - make_interval(secs => ?)",
        (user_id, CACHE_TTL.total_seconds())
    ).fetchone()

    conn.close()

    return row["summary"] if row else None


def _save_cached_summary(user_id, summary):
    conn = get_crm_connection()

    conn.execute("""
        INSERT INTO executive_summary_cache (user_id, summary, generated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (user_id) DO UPDATE SET
            summary = excluded.summary,
            generated_at = excluded.generated_at
    """, (user_id, summary))

    conn.commit()
    conn.close()


def generate_executive_summary(user_id, dashboard, force_refresh=False):

    if not force_refresh:
        cached = _get_cached_summary(user_id)
        if cached is not None:
            return cached

    prompt = f"""
You are a CRM sales director.

Using the dashboard below, write a concise executive summary.

Requirements:
- Maximum 120 words
- Professional tone
- Highlight strengths
- Highlight risks
- Recommend top priorities
- No markdown
- Plain text only

Dashboard:
{dashboard}
"""

    try:
        summary = ask_llm(
            system_prompt="You are an experienced Sales Director.",
            user_prompt=prompt
        )

        summary = summary.strip()

        # Caching is a latency/cost optimization, not a correctness
        # requirement - if the write fails for any reason, still return
        # the freshly generated summary rather than erroring the whole
        # dashboard load over it.
        try:
            _save_cached_summary(user_id, summary)
        except Exception:
            pass

        return summary

    except Exception:
        return "Executive summary unavailable."
