import os
import json
import hashlib
from datetime import datetime

TRACKER_DIR = "data/doc_registry"


def _get_user_file(user_id: str):
    os.makedirs(TRACKER_DIR, exist_ok=True)
    return os.path.join(TRACKER_DIR, f"{user_id}.json")


def load_registry(user_id: str):
    path = _get_user_file(user_id)

    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(user_id: str, data: dict):
    path = _get_user_file(user_id)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def update_doc(user_id, url, content_hash, chunk_count):

    path = _path(user_id)

    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
    else:
        data = {}

    data[url] = {
        "hash": content_hash,
        "chunk_count": chunk_count
    }

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def is_changed(user_id, url, new_hash):

    path = _path(user_id)

    if not os.path.exists(path):
        return True  # first time always index

    with open(path, "r") as f:
        data = json.load(f)

    old = data.get(url, {}).get("hash")

    return old != new_hash


def get_indexed_pages(user_id):
    """
    Returns the currently indexed pages for this user as a list of
    {"url": ..., "chunk_count": ...} dicts, sorted by url - the shape the
    Settings page's "pages indexed" list is built from.
    """

    registry = load_registry(user_id)

    return sorted(
        (
            {
                "url": url,
                "chunk_count": info.get("chunk_count", 0)
            }
            for url, info in registry.items()
        ),
        key=lambda page: page["url"]
    )


def clear_registry(user_id):
    """
    Wipes all indexed-page tracking for this user - used when their one
    website is deleted entirely, so the Settings page doesn't keep showing
    pages from a site that's no longer configured.
    """

    save_registry(user_id, {})


def _path(user_id):
    os.makedirs("data/doc_registry", exist_ok=True)
    return f"data/doc_registry/{user_id}.json"