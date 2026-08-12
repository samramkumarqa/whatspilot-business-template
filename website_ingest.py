import hashlib
import trafilatura

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from site_discovery import discover_site_pages


def get_hash(text: str) -> str:
    return hashlib.md5(
        text.encode("utf-8")
    ).hexdigest()


def load_website_chunks(user_id):
    filepath = f"data/websites/{user_id}.txt"

    try:

        with open(
            filepath,
            "r",
            encoding="utf-8"
        ) as f:

            root_urls = list(
                set(
                    line.strip()
                    for line in f
                    if line.strip()
                )
            )

        # Each business only ever has one root URL on file (see
        # website_manager.py's MAX_WEBSITES_PER_USER), but that root page
        # is rarely the whole site - discover_site_pages() expands it into
        # up to MAX_PAGES_PER_SITE real pages (sitemap-first, capped) so a
        # reindex actually captures the site's content instead of just the
        # homepage.
        urls = []
        seen_urls = set()

        for root_url in root_urls:

            for url in discover_site_pages(root_url):

                if url not in seen_urls:
                    seen_urls.add(url)
                    urls.append(url)

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150
        )

        results = []

        for url in urls:

            try:

                print(f"🌐 Loading: {url}")

                downloaded = trafilatura.fetch_url(url)

                if not downloaded:
                    print(f"❌ Failed to fetch: {url}")
                    continue

                text = trafilatura.extract(
                    downloaded,
                    include_links=True,
                    include_tables=True,
                    include_comments=False,
                    favor_recall=True
                )

                if not text or len(text.strip()) < 200:
                    print(
                        f"⚠️ Skipping low-quality content: {url}"
                    )
                    continue

                content_hash = get_hash(text)

                doc = Document(
                    page_content=text,
                    metadata={
                        "source": url,
                        "source_type": "website",
                        "url": url
                    }
                )

                website_chunks = splitter.split_documents(
                    [doc]
                )

                for chunk in website_chunks:
                    chunk.metadata["url"] = url

                results.append({
                    "url": url,
                    "chunks": website_chunks,
                    "hash": content_hash
                })

                print(
                    f"✅ {url} → {len(website_chunks)} chunks"
                )

            except Exception as e:

                print(f"❌ Failed: {url}")
                print(e)

        return results

    except FileNotFoundError:

        print("⚠️ websites.txt not found")
        return []