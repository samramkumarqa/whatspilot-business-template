"""
Load test for POST /webhook - simulates concurrent incoming WhatsApp
messages the way Twilio would actually deliver them, including a
genuinely valid X-Twilio-Signature header (computed with your real
TWILIO_AUTH_TOKEN from .env, via the same twilio-python RequestValidator
the app itself uses to check it) - so this exercises the real signature
validation path too, not a DEBUG-mode bypass.

WHAT IT SIMULATES
------------------
Each simulated request is a different (fake, synthetic) customer phone
number messaging your real business WhatsApp number. --customers controls
how many distinct fake numbers are cycled through; --requests controls how
many total messages get sent (so requests > customers means some
"customers" send more than one message, growing their conversation
history like a real repeat customer would).

SAFETY
------
- Only runs against localhost/127.0.0.1 by default - pass --force to
  target anything else (e.g. a real Render URL), which is NOT
  recommended: it would use real Groq/Twilio quota and could affect
  real customer traffic.
- Run your local server with LOAD_TEST_MODE=true (see config.py) so it
  skips the real outbound Twilio send at the end of each request -
  otherwise this will attempt to send real WhatsApp messages to
  fake/synthetic numbers, which will mostly fail but still costs a real
  Twilio API call each time.
- Synthetic customer numbers all start with +19999990 so they're easy to
  spot and clean out of your local test database afterward, e.g.:
      DELETE FROM leads WHERE customer_phone LIKE '+19999990%';
      DELETE FROM customer_mapping WHERE customer_phone LIKE '+19999990%';

USAGE
-----
    DATABASE_URL=... python load_test_webhook.py \\
        --to +14155238886 \\
        --requests 50 \\
        --concurrency 5

--to must be a WhatsApp number already registered as this business's
whatsapp_number in the tenant registry (customer_numbers table) and
active - i.e. the same number your real customers message. The script
reads TWILIO_AUTH_TOKEN and, if --to is omitted, TWILIO_WHATSAPP_NUMBER
from this directory's .env.
"""

import argparse
import asyncio
import statistics
import time
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
import os

from twilio.request_validator import RequestValidator

load_dotenv()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000/webhook", help="Webhook URL (default: %(default)s)")
    parser.add_argument("--to", default=os.getenv("TWILIO_WHATSAPP_NUMBER"), help="Your business's WhatsApp number, e.g. +14155238886 (default: TWILIO_WHATSAPP_NUMBER from .env)")
    parser.add_argument("--requests", "-n", type=int, default=50, help="Total messages to send (default: %(default)s)")
    parser.add_argument("--concurrency", "-c", type=int, default=5, help="Max requests in flight at once (default: %(default)s)")
    parser.add_argument("--customers", type=int, default=None, help="Distinct synthetic customer numbers to cycle through (default: same as --concurrency)")
    parser.add_argument("--message", default="What are your business hours?", help="Message body to send (default: %(default)r)")
    parser.add_argument("--auth-token", default=os.getenv("TWILIO_AUTH_TOKEN"), help="Override TWILIO_AUTH_TOKEN (default: from .env)")
    parser.add_argument("--force", action="store_true", help="Allow targeting a non-localhost URL (NOT recommended)")
    return parser.parse_args()


def make_signature(validator, url, form_data):
    # Mirrors api/webhook.py: it validates against the https:// form of
    # its own URL regardless of what scheme it was actually reached on
    # (Render terminates TLS in front of it) - the signature has to be
    # computed the same way or it'll never match.
    https_url = url.replace("http://", "https://", 1)
    return validator.compute_signature(https_url, form_data)


async def send_one(client, url, validator, to_number, from_number, message, sem, results, index):
    form_data = {
        "From": f"whatsapp:{from_number}",
        "To": f"whatsapp:{to_number}",
        "Body": message,
        "ProfileName": f"Load Test Customer {index}",
    }

    signature = make_signature(validator, url, form_data)

    async with sem:
        start = time.perf_counter()
        try:
            resp = await client.post(
                url,
                data=form_data,
                headers={"X-Twilio-Signature": signature},
                timeout=60.0,
            )
            elapsed = time.perf_counter() - start

            ok = resp.status_code == 200
            body_status = None
            try:
                body_status = resp.json().get("status")
            except Exception:
                pass

            results.append({
                "elapsed": elapsed,
                "http_status": resp.status_code,
                "ok": ok and body_status != "error",
                "body_status": body_status,
                "detail": None if ok else resp.text[:200],
            })

        except Exception as e:
            elapsed = time.perf_counter() - start
            results.append({
                "elapsed": elapsed,
                "http_status": None,
                "ok": False,
                "body_status": None,
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

    if not args.to:
        raise SystemExit(
            "No --to given and TWILIO_WHATSAPP_NUMBER isn't set in .env - "
            "pass the business WhatsApp number this deployment listens on."
        )

    if not args.auth_token:
        raise SystemExit(
            "No --auth-token given and TWILIO_AUTH_TOKEN isn't set in .env "
            "- needed to compute a valid X-Twilio-Signature."
        )

    host = urlparse(args.url).hostname or ""
    if host not in ("localhost", "127.0.0.1") and not args.force:
        raise SystemExit(
            f"Refusing to target {args.url!r} - looks like it isn't your "
            f"local dev server. Pass --force to override (not recommended: "
            f"this would use real Groq/Twilio quota against a live app)."
        )

    n_customers = args.customers or args.concurrency
    customers = [f"+19999990{str(i).zfill(3)}" for i in range(n_customers)]

    validator = RequestValidator(args.auth_token)
    sem = asyncio.Semaphore(args.concurrency)
    results = []

    print(f"Target:        {args.url}")
    print(f"Business (To): {args.to}")
    print(f"Requests:      {args.requests}")
    print(f"Concurrency:   {args.concurrency}")
    print(f"Customers:     {n_customers} synthetic numbers ({customers[0]} ... {customers[-1]})")
    print()
    print("Running...")

    start_wall = time.perf_counter()

    async with httpx.AsyncClient() as client:
        tasks = [
            send_one(
                client, args.url, validator,
                args.to, customers[i % n_customers], args.message,
                sem, results, i,
            )
            for i in range(args.requests)
        ]
        await asyncio.gather(*tasks)

    wall_time = time.perf_counter() - start_wall

    latencies_ms = sorted(r["elapsed"] * 1000 for r in results)
    successes = [r for r in results if r["ok"]]
    failures = [r for r in results if not r["ok"]]

    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total requests:   {len(results)}")
    print(f"Succeeded:        {len(successes)}")
    print(f"Failed:           {len(failures)}")
    print(f"Wall time:        {wall_time:.2f}s")
    print(f"Throughput:       {len(results) / wall_time:.2f} req/s")
    print()
    if latencies_ms:
        print("Latency (ms):")
        print(f"  min:    {min(latencies_ms):.0f}")
        print(f"  mean:   {statistics.mean(latencies_ms):.0f}")
        print(f"  median: {statistics.median(latencies_ms):.0f}")
        print(f"  p95:    {percentile(latencies_ms, 0.95):.0f}")
        print(f"  p99:    {percentile(latencies_ms, 0.99):.0f}")
        print(f"  max:    {max(latencies_ms):.0f}")

    if failures:
        print()
        print(f"First {min(5, len(failures))} failure(s):")
        for f in failures[:5]:
            print(f"  http={f['http_status']} body_status={f['body_status']} detail={f['detail']}")

    print()
    print(f"Cleanup: synthetic customers used +19999990000 .. +19999990{str(n_customers - 1).zfill(3)}")
    print("  DELETE FROM leads WHERE customer_phone LIKE '+19999990%';")
    print("  DELETE FROM customer_mapping WHERE customer_phone LIKE '+19999990%';")


if __name__ == "__main__":
    asyncio.run(main())
