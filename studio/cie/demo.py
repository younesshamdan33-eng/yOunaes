import argparse
from . import engine

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("idea")
    ap.add_argument("--seconds", type=int, default=300)
    ap.add_argument("--look", default="cinematic")
    a = ap.parse_args()
    p = engine.plan({"idea": a.idea, "target_seconds": a.seconds, "look": a.look})
    print("planner:", p["planner"], "| language:", p["language"], "| logline:", p["logline"])
    print("characters:", [(c["name"], c["role"]) for c in p["memory"]["characters"].values()])
    print("locations:", [(l["name"], l["kind"]) for l in p["memory"]["locations"].values()])
    print("totals:", p["totals"])
    for w in p["warnings"]:
        print("WARNING:", w)
    for sc in p["scenes"][:3]:
        print("\n[%s] %s (%s)\n   %s" % (sc["id"], sc["title"], sc["beat"], sc["text"]))
        for sh in sc["shots"][:2]:
            print("   -", sh["id"], "%ds" % sh["seconds"], sh["prompt"][:230])

if __name__ == "__main__":
    main()
