from database.db import get_crm_connection


def get_connection():
    return get_crm_connection()


def init_tags():
    conn = get_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS customer_tags (
        customer_phone TEXT NOT NULL,
        tag TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (customer_phone, tag)
    )
    """)

    conn.commit()
    conn.close()


def delete_tags(customer_phone):
    conn = get_connection()

    conn.execute(
        """
        DELETE FROM customer_tags
        WHERE customer_phone=?
        """,
        (customer_phone,)
    )

    conn.commit()
    conn.close()


def save_tags(customer_phone, tags):
    """
    Replace existing tags with the new list.
    """

    if tags is None:
        tags = []

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM customer_tags
        WHERE customer_phone=?
        """,
        (customer_phone,)
    )

    for tag in tags:

        conn.execute(
            """
            INSERT INTO customer_tags
            (
                customer_phone,
                tag
            )
            VALUES (?, ?)
            ON CONFLICT (customer_phone, tag) DO NOTHING
            """,
            (
                customer_phone,
                tag
            )
        )

    conn.commit()
    conn.close()


def get_tags(customer_phone):

    conn = get_connection()

    cursor = conn.execute(
        """
        SELECT tag
        FROM customer_tags
        WHERE customer_phone=?
        ORDER BY tag
        """,
        (customer_phone,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [row[0] for row in rows]


def add_tag(customer_phone, tag):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO customer_tags
        (
            customer_phone,
            tag
        )
        VALUES (?, ?)
        ON CONFLICT (customer_phone, tag) DO NOTHING
        """,
        (
            customer_phone,
            tag
        )
    )

    conn.commit()
    conn.close()


def remove_tag(customer_phone, tag):

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM customer_tags
        WHERE customer_phone=?
        AND tag=?
        """,
        (
            customer_phone,
            tag
        )
    )

    conn.commit()
    conn.close()


def find_customers_by_tag(tag):

    conn = get_connection()

    cursor = conn.execute(
        """
        SELECT customer_phone
        FROM customer_tags
        WHERE tag=?
        ORDER BY customer_phone
        """,
        (tag,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [row[0] for row in rows]