import os
from urllib.parse import urlparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

WEBSITE_DIR = BASE_DIR / "data" / "websites"

os.makedirs(
    WEBSITE_DIR,
    exist_ok=True
)

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

    website_file = get_user_file(user_id)

    if not os.path.exists(website_file):
        return []

    with open(
        website_file,
        "r",
        encoding="utf-8"
    ) as f:

        return [
            normalize_url(line)
            for line in f.readlines()
            if line.strip()
        ]

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

    website_file = get_user_file(user_id)

    with open(
        website_file,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(url + "\n")

    return "added"

def delete_website(user_id, url):

    url = normalize_url(url)

    websites = get_websites(user_id)

    if url not in websites:
        return False

    websites.remove(url)

    website_file = get_user_file(user_id)

    with open(
        website_file,
        "w",
        encoding="utf-8"
    ) as f:

        for site in websites:
            f.write(site + "\n")

    return True

def get_user_file(user_id):

    return WEBSITE_DIR / f"{user_id}.txt"