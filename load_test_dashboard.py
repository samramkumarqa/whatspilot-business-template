"""
Load test for the dashboard/API surface - simulates a business owner's
browser loading the dashboard, hitting the same GET endpoints
dashboard.html fires off on page load, concurrently and repeatedly.

AUTH
----
Rather than driving the real OTP login flow (which needs a live Twilio
Verify round trip per session), this forges a session cookie the exact
same way Starlette's SessionMiddleware itself signs one - using your
real SESSION_SECRET_KEY from .env. This isn't a bypass of anything: it's
only usable by someone who already has the secret key your own server
is running with, i.e. you. Session shape mirrors what
api/auth.py's business_login_verify_submit() actually sets after a real
OTP check succeeds.

SAFETY
------
Only runs against localhost/127.0.0.1 by default - pass --force to
target anything else (not recommended - it would put real load and
real DB queries against a live app).

USAGE
-----
    python load_test_dashboard.py --user-id +14155550000 --iterations 20 --concurrency 5

--user-id must be a real, active business owner's user_id already
registered in your local test database (the same value used to log in -
often the business's own WhatsApp number). --business-id is optional and
only cosmetic (not actually checked by enforce_tenant_access()) but
included for a faithful session shape; if omitted the script looks it up
via customer_mapping.get_business_id() if it can import your app's code,
otherwise leaves it blank.
"""

import argparse
import asyncio
import base64
import json
import os
import statistics
import time
from urllib.parse import urlparse

import httpx
import itsdangerous
from dotenv import load_dotenv

load_dotenv()

# One full "dashboard page load" - the set of GET endpoints
# templates/dashboard.html actually calls on load/refresh. Edit this list
# to add/remove endpoints if your dashboard calls change.
ENDPOINTS = [
    "/dashboard/{user_id}",
    "/stats/{user_id}",
    "/dashboard-metrics/{user_id}",
    "/dashboard/analytics/{user_id}",
    "/sales-funnel/{user_id}",
    "/lead-score-dashboard/{user_id}",
    "/customers/{user_id}",
    "/automation/rules/{user_id}",
    "/reminders?user_id={user_id}",
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL (default: %(default)s)")
    parser.add_argument("--user-id", required=True, help="Business owner's user_id (required)")
    parser.add_argument("--business-id", default="", help="Optional - cosmetic only, not checked by auth")
    parser.add_argument("--secret", default=os.getenv("SESSION_SECRET_KEY"), help="Override SESSION_SECRET_KEY (default: from .env)")
    parser.add_argument("--iterations", "-n", type=int, default=20, help="Full page-load cycles to run (default: %(default)s)")
    parser.add_argument("--concurrency", "-c", type=int, default=5, help="Max concurrent page-load cycles (default: %(default)s)")
    parser.add_argument("--force", action="store_true", help="Allow targeting a non-localhost URL (NOT recommended)")
    return parser.parse_args()


def forge_session_cookie(secret_key, user_id, business_id):
    # Exactly mirrors starlette.middleware.sessions.SessionMiddleware's
    # own signing (itsdangerous.TimestampSigner over base64-encoded JSON) -
    # see that module's source if this ever needs re-verifying against a
    # starlette version bump.
    session = {
        "role": "business_owner",
        "user_id": user_id,
        "business_id": business_id,
    }
    signer = itsdangerous.TimestampSigner(str(secret_key))
    data = base64.b64encode(json.dumps(session).encode("utf-8"))
    return signer.sign(data).decode("utf-8")


async def load_one_page(client, base_url, user_id, sem, results):
    async with sem:
        for path_template in ENDPOINTS:
            path = path_template.format(user_id=user_id)
            url = base_url + path
            start = time.perf_counter()
            try:
                resp = await client.get(url, timeout=30.0)
                elapsed = time.perf_counter() - start
                results.append({
                    "endpoint": path_template,
                    "elapsed": elapsed,
                    "http_status": resp.status_code,
                    "ok": resp.status_code == 200,
                    "detail": None if resp.status_code == 200 else resp.text[:200],
                })
            except Exception as e:
                elapsed = time.perf_counter() - start
                results.append({
                    "endpoint": path_template,
                    "elapsed": elapsed,
                    "http_status": None,
                    "ok": False,
                    "detail": str(e)[:200],
                })


def percentile(sorted_values, pct):
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


async def main():
    args = parse_args()

    if not args.secret:
        raise SystemExit(
            "No --secret given and SESSION_SECRET_KEY isn't set in .env "
            "- needed to forge a valid session cookie."
        )

    host = urlparse(args.url).hostname or ""
    if host not in ("localhost", "127.0.0.1") and not args.force:
        raise SystemExit(
            f"Refusing to target {args.url!r} - looks like it isn't your "
            f"local dev server. Pass --force to override (not recommended)."
        )

    cookie_value = forge_session_cookie(args.secret, args.user_id, args.business_id)
    sem = asyncio.Semaphore(args.concurrency)
    results = []

    print(f"Target:       {args.url}")
    print(f"User:         {args.user_id}")
    print(f"Iterations:   {args.iterations} full page-load cycles ({len(ENDPOINTS)} endpoints each = {args.iterations * len(ENDPOINTS)} requests)")
    print(f"Concurrency:  {args.concurrency}")
    print()
    print("Running...")

    start_wall = time.perf_counter()

    async with httpx.AsyncClient(cookies={"wp_session": cookie_value}) as client:
        # Sanity check the session actually works before burning a whole
        # run on what would otherwise be 401/403s for every request.
        probe = await client.get(f"{args.url}/dashboard/{args.user_id}", timeout=30.0)
        if probe.status_code != 200:
            raise SystemExit(
                f"Auth check failed - GET /dashboard/{args.user_id} returned "
                f"{probe.status_code}: {probe.text[:300]}\n"
                f"Check --user-id is a real, active business owner in your "
                f"local test DB and --secret matches your running server's "
                f"SESSION_SECRET_KEY."
            )

        tasks = [
            load_one_page(client, args.url, args.user_id, sem, results)
            for _ in range(args.iterations)
        ]
        await asyncio.gather(*tasks)

    wall_time = time.perf_counter() - start_wall

    latencies_ms = sorted(r["elapsed"] * 1000 for r in results)
    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]

    print()
    print("=" * 60)
    print("OVERALL")
    print("=" * 60)
    print(f"Total requests:   {len(results)}")
    print(f"Succeeded:        {len(successes)}")
    print(f"Failed:           {len(failures)}")
    print(f"Wall time:        {wall_time:.2f}s")
    print(f"Throughput:       {len(results) / wall_time:.2f} req/s")
    if latencies_ms:
        print()
        print("Latency across all endpoints (ms):")
        print(f"  min:    {min(latencies_ms):.0f}")
        print(f"  mean:   {statistics.mean(latencies_ms):.0f}")
        print(f"  median: {statistics.median(latencies_ms):.0f}")
        print(f"  p95:    {percentile(latencies_ms, 0.95):.0f}")
        print(f"  p99:    {percentile(latencies_ms, 0.99):.0f}")
        print(f"  max:    {max(latencies_ms):.0f}")

    print()
    print("=" * 60)
    print("BY ENDPOINT (mean latency)")
    print("=" * 60)
    by_endpoint = {}
    for r in results:
        by_endpoint.setdefault(r["endpoint"], []).append(r["elapsed"] * 1000)
    for endpoint, values in sorted(by_endpoint.items(), key=lambda kv: -statistics.mean(kv[1])):
        print(f"  {statistics.mean(values):7.0f} ms  (n={len(values):3d})  {endpoint}")

    if failures:
        print()
        print(f"First {min(5, len(failures))} failure(s):")
        for f in failures[:5]:
            print(f"  {f['endpoint']}: http={f['http_status']} detail={f['detail']}")


if __name__ == "__main__":
    asyncio.run(main())
