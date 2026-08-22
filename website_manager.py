from database.db import get_crm_connection

# Used to live on local disk (data/websites/{user_id}.txt) - moved to
# Postgres's indexed_websites table (see
# vector_store.init_website_index()) so the configured website URL
# survives Render's free-tier restarts, same reason doc_tracker.py and
# vector_store.py moved.

# Each business's AI assistant is only meant to answer from one site's
# indexed content - allowing more than one silently mixes two businesses'
# knowledge bases into a single AI reply with no way to tell them apart.
MAX_WEBSITES_PER_USER = 1


def normalize_url(url):

    url = url.strip()

    if url.endswith("/"):
        url = url[:-1]

    return url


def get_websites(user_id):

    conn = get_crm_connection()

    try:

        rows = conn.execute(
            "SELECT url FROM indexed_websites "
            "WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ).fetchall()

    finally:
        conn.close()

    return [row[0] for row in rows]


def add_website(user_id, url):
    """
    Adds a website to be indexed for this user.

    Returns one of:
        "added"         - the url was new and has been saved
        "exists"        - this exact url was already indexed
        "limit_reached" - this user already has MAX_WEBSITES_PER_USER
                           website(s) indexed and this url isn't one of them
    """

    url = normalize_url(url)

    print(
        f"ADD WEBSITE CALLED: {user_id} -> {url}"
    )

    websites = get_websites(user_id)

    if url in websites:
        return "exists"

    if len(websites) >= MAX_WEBSITES_PER_USER:
        return "limit_reached"

    conn = get_crm_connection()

    try:

        conn.execute(
            "INSERT INTO indexed_websites (user_id, url) VALUES (?, ?) "
            "ON CONFLICT (user_id, url) DO NOTHING",
            (user_id, url)
        )

        conn.commit()

    finally:
        conn.close()

    return "added"


def delete_website(user_id, url):

    url = normalize_url(url)

    conn = get_crm_connection()

    try:

        cursor = conn.execute(
            "DELETE FROM indexed_websites WHERE user_id = ? AND url = ?",
            (user_id, url)
        )

        removed = cursor.rowcount > 0

        conn.commit()

    finally:
        conn.close()

    return removed
