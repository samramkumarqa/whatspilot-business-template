from website_ingest import load_website_chunks
from vector_store import add_documents, get_user_lock
from doc_tracker import (
    is_changed,
    update_doc
)


def incremental_ingest(user_id: str):

    print(f"🚀 Starting incremental ingest for {user_id}")

    # Crawling/chunking the site is network-bound and doesn't touch
    # Postgres at all - only acquire the per-user lock (see
    # vector_store.py) around the part that actually reads/writes
    # website_chunks, so a live customer query is only blocked for the
    # duration of the actual DB writes below, not for however long
    # fetching up to MAX_PAGES_PER_SITE pages takes.
    data = load_website_chunks(user_id)

    if not data:
        print("⚠️ No data found")
        return

    total_added = 0

    with get_user_lock(user_id):

        for item in data:

            url = item["url"]
            chunks = item["chunks"]
            content_hash = item["hash"]

            # 🔥 SKIP IF NOT CHANGED
            if not is_changed(user_id, url, content_hash):
                print(f"⏭️ Skipping unchanged: {url}")
                continue

            print(f"📄 Indexing: {url}")

            # add_documents() replaces this URL's previously stored
            # chunks rather than appending on top of them - see its
            # docstring in vector_store.py.
            add_documents(user_id, url, chunks)

            update_doc(
                user_id=user_id,
                url=url,
                content_hash=content_hash,
                chunk_count=len(chunks)
            )

            total_added += len(chunks)

    print(f"✅ Ingest completed. Added {total_added} chunks.")