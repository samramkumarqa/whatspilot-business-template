import asyncio, base64, json, os, statistics, sys, time
import httpx, itsdangerous
from twilio.request_validator import RequestValidator
BASE="http://127.0.0.1:8000"; UID="loadtest-owner-1"; TO=os.environ["TO_NUMBER"]
cookie=itsdangerous.TimestampSigner(os.environ["SESSION_SECRET_KEY"]).sign(base64.b64encode(json.dumps({"role":"business_owner","user_id":UID,"business_id":"loadtest-biz-1"}).encode())).decode()
val=RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
DASH=["/dashboard/{u}","/stats/{u}","/dashboard-metrics/{u}","/dashboard/analytics/{u}","/sales-funnel/{u}","/lead-score-dashboard/{u}","/customers/{u}","/automation/rules/{u}","/reminders?user_id={u}"]
def pct(v,p):
    if not v: return 0
    v=sorted(v);k=(len(v)-1)*p;f=int(k);c=min(f+1,len(v)-1);return v[f]+(v[c]-v[f])*(k-f)
async def dash_user(cl,lat,errs):
    for p in DASH:
        t=time.perf_counter()
        try:
            r=await cl.get(BASE+p.format(u=UID),timeout=60)
            ok=r.status_code==200
        except Exception as e: ok=False
        lat.append((time.perf_counter()-t)*1000)
        if not ok: errs.append(p)
async def hook_user(cl,i,lat,errs):
    form={"From":f"whatsapp:+1999999{i%5000:04d}","To":f"whatsapp:{TO}","Body":"What are your business hours?","ProfileName":f"LT {i}"}
    sig=val.compute_signature((BASE+"/webhook").replace("http://","https://"),form)
    t=time.perf_counter()
    try:
        r=await cl.post(BASE+"/webhook",data=form,headers={"X-Twilio-Signature":sig},timeout=90)
        ok=r.status_code==200 and r.json().get("status")!="error"
    except Exception as e: ok=False
    lat.append((time.perf_counter()-t)*1000)
    if not ok: errs.append("webhook")
async def phase(name,users,kind="dash",dur=None):
    lat=[];errs=[]
    limits=httpx.Limits(max_connections=users+10)
    async with httpx.AsyncClient(cookies={"wp_session":cookie},limits=limits) as cl:
        t0=time.perf_counter()
        if kind=="dash": await asyncio.gather(*[dash_user(cl,lat,errs) for _ in range(users)])
        else: await asyncio.gather(*[hook_user(cl,i,lat,errs) for i in range(users)])
        w=time.perf_counter()-t0
    print(f"{name:34s} users={users:4d} reqs={len(lat):5d} err={len(errs):4d} ({100*len(errs)/max(1,len(lat)):4.1f}%) rps={len(lat)/w:7.1f} mean={statistics.mean(lat):6.0f} p95={pct(lat,.95):6.0f} p99={pct(lat,.99):6.0f} max={max(lat):6.0f}ms",flush=True)
async def main():
    mode=sys.argv[1]
    if mode=="stress":
        print("## STRESS - dashboard page loads (9 endpoints each), ramping concurrent users")
        for u in [10,25,50,100,200,400]: await phase("dashboard",u)
        print("## STRESS - webhook, ramping concurrent messages")
        for u in [10,25,50,100,200,400]: await phase("webhook",u,"hook")
    elif mode=="spike":
        print("## SPIKE - 2 users -> 150 -> 2, dashboard")
        await phase("baseline",2); await phase("SPIKE",150); await phase("recovery",2); await phase("recovery2",2)
        print("## SPIKE - webhook 2 -> 150 -> 2")
        await phase("baseline",2,"hook"); await phase("SPIKE",150,"hook"); await phase("recovery",2,"hook")
    elif mode=="volume":
        for u in [1,10,30]: await phase("dashboard",u)
asyncio.run(main())
