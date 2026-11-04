#!/usr/bin/env python3
"""Resume KnowledgeHub transcript import. Captions only; checkpoint per video."""
import os,json,time,urllib.request,urllib.parse,urllib.error
from pathlib import Path
Path("results").mkdir(exist_ok=True)
key=os.environ.get("TRANSCRIPTYT_API_KEY","")
site=os.environ.get("KNOWLEDGEHUB_URL","").rstrip("/")
token=os.environ.get("ADMIN_IMPORT_TOKEN","")
if not all((key,site,token)) or not site.startswith("https://"):
    raise SystemExit("Missing required secrets or invalid KnowledgeHub URL")
maximum=int(os.environ.get("MAX_VIDEOS","10"))
if not 1<=maximum<=717: raise SystemExit("MAX_VIDEOS must be 1..717")
def call(url,headers=None,body=None):
    req=urllib.request.Request(url,headers=headers or {},data=body,method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req,timeout=65) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:
        try: data=json.loads(e.read())
        except Exception: data={"error":"HTTP "+str(e.code)}
        return e.code,data
auth={"Authorization":"Bearer "+token}
code,usage=call("https://transcript-yt.com/v1/usage",auth if False else {"Authorization":"Bearer "+key})
if code!=200: raise SystemExit("Usage lookup failed; no requests made")
available=usage.get("credits_remaining")
if not isinstance(available,(int,float)): raise SystemExit("Unknown credit balance")
maximum=min(maximum,int(available))
if maximum<=0: raise SystemExit("No credits")
code,data=call(site+"/api/admin/videos",auth)
if code!=200: raise SystemExit("Cannot load video catalog")
videos=data.get("videos",[])
code,data=call(site+"/api/admin/transcript-ids",auth)
if code!=200: raise SystemExit("Cannot load existing transcript IDs")
existing=set(data.get("video_ids",[]))
candidates=[v for v in videos if v.get("id") not in existing]
print("Catalog",len(videos),"already saved",len(existing),"remaining",len(candidates),"credits",available,"limit",maximum,flush=True)
results=[]
def checkpoint():
    Path("results/summary.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
last_call=0.
for v in candidates[:maximum]:
    vid=v["id"]
    delay=max(0,8-(time.monotonic()-last_call))
    if delay:time.sleep(delay)
    params=urllib.parse.urlencode({"url":vid,"language":"ru","format":"json","mode":"captions"})
    code,data=call("https://transcript-yt.com/v1/transcript?"+params,{"Authorization":"Bearer "+key,"Accept":"application/json"})
    last_call=time.monotonic()
    if code==429:
        time.sleep(75)
        code,data=call("https://transcript-yt.com/v1/transcript?"+params,{"Authorization":"Bearer "+key,"Accept":"application/json"})
        last_call=time.monotonic()
    item={"video_id":vid,"title":v.get("title","")[:120],"http":code}
    if code!=200 or not isinstance(data,dict):
        item["status"]="api_error"
        item["error"]=str(data.get("error",""))[:150] if isinstance(data,dict) else "invalid response"
        results.append(item);checkpoint()
        print(vid,item["status"],code,flush=True)
        if code in (401,402,403,429) or code>=500 or sum(x["status"]=="api_error" for x in results)>=3:break
        continue
    segments=data.get("segments") or []
    transcript="\n".join(str(s.get("text","")) for s in segments if isinstance(s,dict))
    if not transcript.strip():transcript=str(data.get("text") or "")
    item.update(characters=len(transcript),segments=len(segments),language=data.get("language"),source=data.get("source"))
    item["quality_flag"]="review_short_or_sparse" if len(transcript)<2000 or len(segments)<40 else "needs_duration_comparison"
    if data.get("language")!="ru" or len(transcript)<50:
        item["status"]="invalid_response"
    else:
        payload={"video_id":vid,"transcript":transcript,"source_note":"TranscriptYT API, Russian YouTube captions; automated import, not verified; usage rights require review"}
        save_code,_=call(site+"/api/admin/transcripts",{"Authorization":"Bearer "+token,"Content-Type":"application/json"},json.dumps(payload,ensure_ascii=False).encode())
        item["save_http"]=save_code
        item["status"]="saved" if save_code==200 else "save_error"
    results.append(item);checkpoint()
    print(vid,item["status"],"chars",item["characters"],"quality",item["quality_flag"],flush=True)
    if item["status"]=="save_error":break
code,usage=call("https://transcript-yt.com/v1/usage",{"Authorization":"Bearer "+key})
print("Credits after",usage.get("credits_remaining","unknown") if code==200 else "unknown")
print("SUMMARY",json.dumps({"saved":sum(x["status"]=="saved" for x in results),"failed":sum(x["status"]!="saved" for x in results),"flagged":sum(x.get("quality_flag")=="review_short_or_sparse" for x in results)},ensure_ascii=False))
