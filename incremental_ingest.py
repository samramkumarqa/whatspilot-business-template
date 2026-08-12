from website_ingest import load_website_chunks
from vector_store import get_user_vectorstore
from doc_tracker import (
    is_changed,
    update_doc
)


def incremental_ingest(user_id: str):

    print(f"🚀 Starting incremental ingest for {user_id}")

    data = load_website_chunks(user_id)

    if not data:
        print("⚠️ No data found")
        return

    vectorstore = get_user_vectorstore(user_id)

    total_added = 0

    for item in data:

        url = item["url"]
        chunks = item["chunks"]
        content_hash = item["hash"]

        # 🔥 SKIP IF NOT CHANGED
        if not is_changed(user_id, url, content_hash):
            print(f"⏭️ Skipping unchanged: {url}")
            continue

        print(f"📄 Indexing: {url}")

        vectorstore.add_documents(chunks)

        update_doc(
            user_id=user_id,
            url=url,
            content_hash=content_hash,
            chunk_count=len(chunks)
        )

        total_added += len(chunks)

    print(f"✅ Ingest completed. Added {total_added} chunks.")