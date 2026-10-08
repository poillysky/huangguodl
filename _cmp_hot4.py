import json, re, sys, urllib.parse, urllib.request
sys.path.insert(0,"packages/core")
from hg_core import build_opener, DEFAULT_HEADERS, HGApi
opener = build_opener("http://127.0.0.1:7897")

def get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={**DEFAULT_HEADERS, "Accept": accept})
    with opener.open(req, timeout=25) as r:
        return r.read().decode("utf-8","replace"), r.geturl()

html, final = get("https://huangguoai.com/recommend")
print("final", final)
names = re.findall(r'data-track-title="([^"]+)"', html)
print("track titles", names[:12])
names2 = re.findall(r'"@type":"ListItem","name":"([^"]+)","position"', html)
print("ItemList", names2[:12])
for m in re.finditer(r'API\s*=\s*"((?:\\.|[^"\\])*)"', html):
    s = m.group(1).encode().decode("unicode_escape")
    print("API", s)
q = re.search(r"QUERY\s*=\s*(\{.*?\})", html, re.S)
if q: print("QUERY", q.group(1))
apis = sorted(set(re.findall(r'/api/[^"\\]+', html)))
print("apis", apis)
print("jump", re.findall(r'data-jump-tpl="([^"]+)"', html)[:5])
print("pages", re.findall(r'data-pages="([^"]+)"', html)[:5])

# try recommend APIs
for path in [
    "/api/videos/recommend?page=1&size=12",
    "/api/videos/recommend/?page=1&size=12",
    "/api/recommend?page=1&size=12",
    "/api/videos?page=1&page_size=12&sort=recommend",
    "/api/videos/category/recommend?page=1&size=12",
    "/api/videos/recommend/list?page=1&size=12",
    "/api/videos/recommend/hot?page=1&size=12",
]:
    try:
        text,_=get("https://huangguoai.com"+path, "application/json")
        d=json.loads(text)
        items=((d.get("data") or {}).get("items") if isinstance(d,dict) else None) or []
        print("OK", path, [x.get("title") for x in items[:6]], "n", len(items))
    except Exception as e:
        print("NO", path, e)

# compare homepage 精选 vs our
api = HGApi("https://huangguoai.com", proxy="http://127.0.0.1:7897", timeout=20, retries=1, cache_ttl=0)
our = [s.title for s in api.catalog("hot",1,12)]
print("OUR", our[:8])
home,_=get("https://huangguoai.com/")
# first section grid only
m=re.search(r'精选推荐.*?<div class="hg-card-grid">(.*?)</div>\s*</section>', home, re.S)
if m:
    feat=re.findall(r'data-track-title="([^"]+)"', m.group(1))
    print("HOME featured", feat)
