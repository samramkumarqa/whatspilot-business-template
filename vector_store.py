import threading
import logging

from database.db import get_crm_connection, create_index_if_missing

logger = logging.getLogger(__name__)


_embeddings = None

# fastembed's sentence-transformers/all-MiniLM-L6-v2 (see
# _FastEmbedEmbeddings below) always outputs 384-dimensional vectors -
# website_chunks.embedding below is declared with this fixed size
# because pgvector requires a vector column's dimension to be fixed up
# front.
EMBEDDING_DIM = 384


class _FastEmbedEmbeddings:
    """
    Minimal LangChain Embeddings-compatible wrapper around fastembed's
    TextEmbedding - implements just the two methods this module's own
    add_documents()/similarity_search() call (embed_documents/
    embed_query).

    Uses fastembed instead of langchain_huggingface.HuggingFaceEmbeddings
    (which pulls in sentence-transformers -> torch, ~1-2GB installed) -
    fastembed runs the *same* model (sentence-transformers/all-MiniLM-L6-v2,
    384-dim, ~90MB) via ONNX Runtime instead, so embedding quality is
    unchanged but the app doesn't need torch/transformers at all - this
    is what was OOM-ing every business-portal deployment on Render's
    512MB free tier before this was switched over (see this project's
    earlier "post-boot runtime OOM" history).
    """

    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts):
        return [vec.tolist() for vec in self._model.embed(texts)]

    def embed_query(self, text):
        return next(self._model.embed([text])).tolist()


def get_embeddings():
    """
    Deferred to first use (instead of module level) so a plain app boot
    (auth, dashboard, webhook receiving, CRM, automation - everything
    that doesn't touch the website-RAG feature) doesn't pay the cost of
    loading the embedding model at all.
    """

    global _embeddings
    if _embeddings is None:
        _embeddings = _FastEmbedEmbeddings()
    return _embeddings


# Website indexing used to store everything on the web service's own
# local disk (a Chroma directory here, plus a JSON file in
# doc_tracker.py and a text file in website_manager.py) - Render's free
# tier wipes that disk on every restart/redeploy/idle spin-down (see
# https://render.com/docs/free), so indexed sites and the AI's
# knowledge base kept silently disappearing. Everything now lives in
# Postgres instead - the same shared database every other feature in
# this app already uses, which survives restarts. pgvector (the
# `vector` extension - see enable_pgvector.py) adds the embedding
# column type and the <=> distance operator this module's similarity
# search relies on.

# Postgres's default local persistent backend for the old Chroma setup
# wasn't safe for concurrent access; the equivalent hazard here is two
# requests racing to INSERT/DELETE the same business's rows mid-reindex.
# Kept as a lightweight extra guard (Postgres itself handles the actual
# concurrency safely via row-level locking - this just keeps a single
# business's reindex-then-query sequence coherent from this app's point
# of view). One lock per business, not global, so different businesses'
# indexing/querying still runs in parallel.
_user_locks = {}
_user_locks_guard = threading.Lock()


def get_user_lock(user_id: str) -> threading.Lock:

    with _user_locks_guard:

        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()

        return _user_locks[user_id]


def init_website_index():
    """
    Creates the tables website indexing needs. Deliberately does NOT
    try to CREATE EXTENSION vector itself - see enable_pgvector.py for
    why (a privileged, one-time, database-level operation, not
    something to attempt from every app boot). If that hasn't been run
    yet, the CREATE TABLE below fails with something like 'type
    "vector" does not exist' - caught here and logged as a clear
    warning rather than left to raise, so a website-indexing schema
    problem can never take down the rest of the app (leads,
    conversations, the webhook) which main.py boots unconditionally
    right alongside this.
    """

    conn = get_crm_connection()

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_websites (
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, url)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_pages (
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, url)
            )
        """)

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS website_chunks (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                url TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding VECTOR({EMBEDDING_DIM}) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # No index on the embedding column itself (no ivfflat/hnsw) -
        # each business has at most MAX_PAGES_PER_SITE (25) pages worth
        # of chunks, small enough that a plain sequential scan ordered
        # by <=> is fast, and skips the tuning/maintenance an
        # approximate index needs at this scale.
        create_index_if_missing(
            conn, "idx_website_chunks_user_id",
            "CREATE INDEX idx_website_chunks_user_id "
            "ON website_chunks(user_id)"
        )

        create_index_if_missing(
            conn, "idx_website_chunks_user_url",
            "CREATE INDEX idx_website_chunks_user_url "
            "ON website_chunks(user_id, url)"
        )

        conn.commit()

    except Exception:

        logger.warning(
            "init_website_index() failed - website indexing and the AI "
            "knowledge base will be unavailable until this is fixed. "
            "If the error mentions the \"vector\" type or extension, "
            "run enable_pgvector.py once against this database (see "
            "that file for instructions), then restart this service.",
            exc_info=True
        )

    finally:
        conn.close()


def _to_pgvector_literal(vector):
    """
    pgvector accepts a plain text literal like '[0.1,0.2,...]' cast to
    ::vector - going through psycopg2's normal parameter binding (a
    Python str) rather than the separate `pgvector` package's own type
    adapter keeps this module's only new dependency being pgvector the
    Postgres extension, not an extra Python package on top of it.
    """

    return "[" + ",".join(str(float(x)) for x in vector) + "]"


def _parse_pgvector(raw):
    """
    Without the `pgvector` Python package's type adapter registered,
    psycopg2 hands back a vector column's value as its raw text form
    ("[0.1,0.2,...]") rather than a list - parsed back here for the MMR
    math in similarity_search() below, which needs the actual numbers.
    """

    if raw is None:
        return []

    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]

    return [float(x) for x in str(raw).strip("[]").split(",")]


def add_documents(user_id, url, chunks):
    """
    Embeds and stores this URL's chunks, replacing any chunks
    previously stored for this exact URL.

    Deleting before inserting (rather than only ever appending, which
    is what the old Chroma-based version did) matters once a page's
    content changes: incremental_ingest.py's is_changed() check
    correctly detects the change and calls this again, but without the
    delete here, every past version of that page's content would keep
    accumulating and competing for relevance in every future search
    forever, alongside the current version.
    """

    if not chunks:
        return

    embeddings = get_embeddings()

    texts = [chunk.page_content for chunk in chunks]
    vectors = embeddings.embed_documents(texts)

    conn = get_crm_connection()

    try:

        conn.execute(
            "DELETE FROM website_chunks WHERE user_id = ? AND url = ?",
            (user_id, url)
        )

        for chunk, vector in zip(chunks, vectors):

            conn.execute(
                "INSERT INTO website_chunks "
                "(user_id, url, content, embedding) "
                "VALUES (?, ?, ?, ?::vector)",
                (
                    user_id,
                    url,
                    chunk.page_content,
                    _to_pgvector_literal(vector)
                )
            )

        conn.commit()

    finally:
        conn.close()


def clear_user_vectorstore(user_id: str):
    """
    Wipes all indexed website content for this user - called when their
    last website is deleted (see api/website.py's DELETE /website), so
    old page embeddings don't linger and keep surfacing in AI answers
    after the site itself is gone from Settings.
    """

    conn = get_crm_connection()

    try:

        conn.execute(
            "DELETE FROM website_chunks WHERE user_id = ?",
            (user_id,)
        )

        conn.commit()

    except Exception as e:

        logger.info(
            f"clear_user_vectorstore: nothing to clear for {user_id}: {e}"
        )

    finally:
        conn.close()


def _cosine_similarity(a, b):

    dot = sum(x * y for x, y in zip(a, b))

    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


def _mmr_select(query_vector, candidates, k, lambda_mult=0.5):
    """
    Re-ranks the fetch_k nearest-by-similarity candidates down to k
    using Maximal Marginal Relevance, so the final set favors both
    relevance to the query AND diversity among the results themselves -
    mirrors the old Chroma retriever's search_type="mmr" behavior,
    which this replaces (plain top-k cosine similarity alone tends to
    return several near-duplicate chunks of the same paragraph instead
    of a broader spread of the page's content).
    """

    if len(candidates) <= k:
        return candidates

    query_similarities = [
        _cosine_similarity(query_vector, c["embedding"])
        for c in candidates
    ]

    selected_indices = []
    remaining_indices = list(range(len(candidates)))

    while remaining_indices and len(selected_indices) < k:

        best_index = None
        best_score = None

        for i in remaining_indices:

            if selected_indices:
                redundancy = max(
                    _cosine_similarity(
                        candidates[i]["embedding"],
                        candidates[j]["embedding"]
                    )
                    for j in selected_indices
                )
            else:
                redundancy = 0.0

            score = (
                lambda_mult * query_similarities[i]
                - (1 - lambda_mult) * redundancy
            )

            if best_score is None or score > best_score:
                best_score = score
                best_index = i

        selected_indices.append(best_index)
        remaining_indices.remove(best_index)

    return [candidates[i] for i in selected_indices]


def similarity_search(user_id, query, k=5, fetch_k=20):
    """
    Returns up to k chunks most relevant to `query` for this user, as a
    list of {"content": ..., "source": url} dicts - the Postgres
    replacement for the old Chroma retriever.invoke(query) call.

    Two-step retrieval: pull the fetch_k nearest neighbours by cosine
    distance in SQL (pgvector's <=> operator, which uses the index-free
    sequential scan discussed in init_website_index() at this table
    size), then re-rank down to k with MMR in Python - see
    _mmr_select().
    """

    embeddings = get_embeddings()

    query_vector = embeddings.embed_query(query)

    conn = get_crm_connection()

    try:

        rows = conn.execute(
            "SELECT url, content, embedding "
            "FROM website_chunks "
            "WHERE user_id = ? "
            "ORDER BY embedding <=> ?::vector "
            "LIMIT ?",
            (
                user_id,
                _to_pgvector_literal(query_vector),
                fetch_k
            )
        ).fetchall()

    finally:
        conn.close()

    if not rows:
        return []

    candidates = [
        {
            "source": row[0],
            "content": row[1],
            "embedding": _parse_pgvector(row[2])
        }
        for row in rows
    ]

    selected = _mmr_select(query_vector, candidates, k)

    return [
        {"content": c["content"], "source": c["source"]}
        for c in selected
    ]
