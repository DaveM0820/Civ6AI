import os, zipfile, subprocess
home = os.path.expanduser("~")
src = os.path.join(home, r"OneDrive\Documents\Civ6AI\mp_probe\Civ6AiMpProbe.zip")
out = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=0x08000000).stdout
print("civ6_running", any(n in out for n in ("CivilizationVI.exe", "CivilizationVI_DX12.exe")))
bases = [os.path.join(home, r"Documents\My Games\Sid Meier's Civilization VI"),
         os.path.join(home, r"OneDrive\Documents\My Games\Sid Meier's Civilization VI")]
for b in bases:
    if not os.path.isdir(b):
        print("missing", b); continue
    mods = os.path.join(b, "Mods")
    os.makedirs(mods, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(mods)
    print("installed", os.path.join(mods, "Civ6AiMpProbe"), sorted(os.listdir(os.path.join(mods, "Civ6AiMpProbe"))))
    logs = os.path.join(b, "Logs")
    if os.path.isdir(logs):
        names = sorted(os.listdir(logs))
        print("logs", b, len(names), [n for n in names if "oos" in n.lower() or "sync" in n.lower() or n.lower().startswith("net")])
    ao = os.path.join(b, "AppOptions.txt")
    if os.path.isfile(ao):
        for line in open(ao, encoding="utf-8", errors="replace"):
            s = line.strip()
            if s and not s.startswith(";") and any(k in s.lower() for k in ("log", "tuner", "debug")):
                print("appoption", b[-45:], s)
