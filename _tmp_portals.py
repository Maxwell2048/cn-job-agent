import sys, io, yaml, re, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
d = yaml.safe_load(open("data/seed/campus_2027.yaml", encoding="utf-8"))
cs = d["companies"]
print("companies:", len(cs))
def plat(p):
    p = (p or "").lower()
    for k in ("zhiye.com","mokahr.com","moka","beisen","italent","dayee","dayi","feishu","hotjob","liepin","lagou","51job","zhaopin","campus.","join.","hr.","hire."):
        if k in p: return k
    return "other"
cnt = collections.Counter(plat(c.get("portal","")) for c in cs)
print(dict(cnt))
print("--- portal per company ---")
for c in cs:
    print("%-24s %-14s %-9s %s" % (c["key"], plat(c.get("portal","")), c["sector"], c.get("portal","")))
