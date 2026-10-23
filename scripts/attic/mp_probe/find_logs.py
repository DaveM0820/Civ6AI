import os
b = os.path.join(os.environ["LOCALAPPDATA"], "Firaxis Games", "Sid Meier's Civilization VI")
print("base", b, os.path.isdir(b))
l = os.path.join(b, "Logs")
if os.path.isdir(l):
    n = sorted(os.listdir(l))
    print("count", len(n))
    print([x for x in n if any(k in x.lower() for k in ("oos", "sync", "net", "lua.log"))])
ao = os.path.join(b, "AppOptions.txt")
if os.path.isfile(ao):
    for s in open(ao, errors="replace"):
        s = s.strip()
        if s and not s.startswith(";") and any(k in s.lower() for k in ("log", "tuner", "debug")):
            print("opt", s)
