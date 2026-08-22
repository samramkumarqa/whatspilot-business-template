from database.db import get_crm_connection

# Used to live on local disk (data/doc_registry/{user_id}.json) - moved
# to Postgres's indexed_pages table (see vector_store.init_website_index())
# so this survives Render's free-tier restarts. Function names/signatures
# are unchanged so incremental_ingest.py and api/website.py didn't need
# to change at all.


def update_doc(user_id, url, content_hash, chunk_count):

    conn = get_crm_connection()

    try:

        conn.execute(
            """
            INSERT INTO indexed_pages
                (user_id, url, content_hash, chunk_count, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, url) DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                chunk_count = EXCLUDED.chunk_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, url, content_hash, chunk_count)
        )

        conn.commit()

    finally:
        conn.close()


def is_changed(user_id, url, new_hash):

    conn = get_crm_connection()

    try:

        row = conn.execute(
            "SELECT content_hash FROM indexed_pages "
            "WHERE user_id = ? AND url = ?",
            (user_id, url)
        ).fetchone()

    finally:
        conn.close()

    if not row:
        return True  # first time always index

    return row[0] != new_hash


def get_indexed_pages(user_id):
    """
    Returns the currently indexed pages for this user as a list of
    {"url": ..., "chunk_count": ...} dicts, sorted by url - the shape the
    Settings page's "pages indexed" list is built from.
    """

    conn = get_crm_connection()

    try:

        rows = conn.execute(
            "SELECT url, chunk_count FROM indexed_pages "
            "WHERE user_id = ? ORDER BY url",
            (user_id,)
        ).fetchall()

    finally:
        conn.close()

    return [
        {"url": row[0], "chunk_count": row[1]}
        for row in rows
    ]


def clear_registry(user_id):
    """
    Wipes all indexed-page tracking for this user - used when their one
    website is deleted entirely, so the Settings page doesn't keep showing
    pages from a site that's no longer configured.
    """

    conn = get_crm_connection()

    try:

        conn.execute(
            "DELETE FROM indexed_pages WHERE user_id = ?",
            (user_id,)
        )

        conn.commit()

    finally:
        conn.close()
