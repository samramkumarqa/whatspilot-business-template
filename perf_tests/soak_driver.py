"""
Soak test driver (steady mixed load for a long time, watching latency
drift, memory, threads and Postgres connections).

Run against a LOCAL copy of the app (never production: the webhook half
writes synthetic customers and, unless LOAD_TEST_MODE=true, calls Groq and
Twilio). From whatspilot-business-repo/:

    export DATABASE_URL=postgresql://...local test db...
    export BUSINESS_ID=loadtest-biz-1 SESSION_SECRET_KEY=<random> DEBUG=false LOAD_TEST_MODE=true
    uvicorn main:app --port 8000 &            # note its PID
    # register the test business: save_customer_number('loadtest-owner-1', '<TWILIO_WHATSAPP_NUMBER without whatsapp:>', 'loadtest-biz-1')
    psql "$DATABASE_URL" -v tonum="'+14155238886'" -f perf_tests/seed_volume.sql   # optional 10k-customer dataset
    APP_PID=<uvicorn pid> TO_NUMBER=+14155238886 TWILIO_AUTH_TOKEN=<from .env> SOAK_SECONDS=1800 \\
        python perf_tests/soak_driver.py

Prints one line per 30s. Healthy = flat RSS_MB/threads, pg_conns <= 10
(pool max), no errors, last-2-minutes latency ~= first-2-minutes latency.
"""
import asyncio, base64, json, os, statistics, time, httpx, itsdangerous, psycopg2
from twilio.request_validator import RequestValidator
BASE="http://127.0.0.1:8000"; UID="loadtest-owner-1"; TO=os.environ["TO_NUMBER"]; DUR=int(os.environ.get("SOAK_SECONDS","540")); WIN=30
cookie=itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"]).sign(base64.b64encode(json.dumps({"role":"business_owner","user_id":UID,"business_id":"loadtest-biz-1"}).encode())).decode()
val=RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
LIGHT=["/stats/{u}","/dashboard-metrics/{u}","/dashboard/analytics/{u}","/sales-funnel/{u}","/lead-score-dashboard/{u}","/customer-details/{u}?limit=100","/reminders?user_id={u}&limit=200","/automation/rules/{u}"]
samples=[]; errs=[]; start=time.time()
def rss(pid):
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmRSS"): return int(l.split()[1])//1024
def threads(pid): return len(os.listdir(f"/proc/{pid}/task"))
async def user(cl,kind,i):
    n=0
    while time.time()-start<DUR:
        n+=1
        if kind=="dash":
            for p in LIGHT+(["/dashboard/{u}"] if n%5==0 else []):
                t=time.perf_counter()
                try: r=await cl.get(BASE+p.format(u=UID),timeout=60); ok=r.status_code==200
                except Exception: ok=False
                samples.append((time.time()-start,"dash",(time.perf_counter()-t)*1000,ok))
                if not ok: errs.append(p)
            await asyncio.sleep(1.0)
        else:
            f={"From":f"whatsapp:+1777{(i*1000+n)%9000:04d}","To":f"whatsapp:{TO}","Body":"What are your business hours?","ProfileName":"Soak"}
            sig=val.compute_signature((BASE+"/webhook").replace("http://","https://"),f)
            t=time.perf_counter()
            try: r=await cl.post(BASE+"/webhook",data=f,headers={"X-Twilio-Signature":sig},timeout=60); ok=r.status_code==200 and r.json().get("status")!="error"
            except Exception: ok=False
            samples.append((time.time()-start,"hook",(time.perf_counter()-t)*1000,ok))
            if not ok: errs.append("webhook")
            await asyncio.sleep(0.5)
async def monitor(pid,dsn):
    print(f"{'t(s)':>5} {'dash_req':>8} {'dash_p95':>8} {'hook_req':>8} {'hook_p95':>8} {'errs':>5} {'RSS_MB':>7} {'threads':>7} {'pg_conns':>8}",flush=True)
    last=0
    while time.time()-start<DUR+WIN:
        await asyncio.sleep(WIN); t=time.time()-start
        w=[s for s in samples if last<=s[0]<t]; last=t
        d=[s[2] for s in w if s[1]=="dash"]; h=[s[2] for s in w if s[1]=="hook"]
        p95=lambda v: sorted(v)[int(.95*(len(v)-1))] if v else 0
        c=psycopg2.connect(dsn);cur=c.cursor();cur.execute("select count(*) from pg_stat_activity where datname='postgres'");pc=cur.fetchone()[0];c.close()
        print(f"{t:5.0f} {len(d):8d} {p95(d):8.0f} {len(h):8d} {p95(h):8.0f} {sum(1 for s in w if not s[3]):5d} {rss(pid):7d} {threads(pid):7d} {pc:8d}",flush=True)
        if t>=DUR: break
async def main():
    pid=int(os.environ["APP_PID"]); dsn=os.environ["DATABASE_URL"]
    async with httpx.AsyncClient(cookies={"wp_session":cookie},limits=httpx.Limits(max_connections=60)) as cl:
        await asyncio.gather(monitor(pid,dsn),*[user(cl,"dash",i) for i in range(10)],*[user(cl,"hook",i) for i in range(4)])
    allok=[s for s in samples]; print(f"TOTAL requests={len(allok)} errors={sum(1 for s in allok if not s[3])}")
    for kind in ("dash","hook"):
        for name,a,b in (("first 2 min",0,120),("last 2 min",DUR-120,DUR)):
            v=[s[2] for s in samples if s[1]==kind and a<=s[0]<b]
            if v: print(f"  {kind} {name}: n={len(v)} mean={statistics.mean(v):.0f}ms p95={sorted(v)[int(.95*(len(v)-1))]:.0f}ms")
asyncio.run(main())
