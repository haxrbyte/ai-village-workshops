"""
Run picklescan on one file and print JSON.

Lives outside the service's own environment because the service runs TWO
picklescan versions (see app.py) and you cannot import two versions of the same
package into one interpreter. Each venv executes this file.

Written defensively: picklescan 0.0.15 and 1.0.5 are four years apart and their
ScanResult does not carry the same fields.
"""

import json
import sys

from picklescan.scanner import scan_file_path


def main() -> int:
    try:
        r = scan_file_path(sys.argv[1])
    except Exception as e:  # a scanner that dies IS a result worth reporting
        print(json.dumps({"crashed": True, "error": f"{type(e).__name__}: {e}"}))
        return 0

    globs = []
    for g in getattr(r, "globals", []) or []:
        safety = getattr(g, "safety", None)
        globs.append({
            "module": getattr(g, "module", "?"),
            "name": getattr(g, "name", "?"),
            "safety": str(getattr(safety, "value", safety)).lower(),
        })

    print(json.dumps({
        "crashed": False,
        "issues": getattr(r, "issues_count", 0),
        "suspicious": getattr(r, "suspicious_count", None),
        "scan_err": bool(getattr(r, "scan_err", False)),
        "scanned_files": getattr(r, "scanned_files", None),
        "infected_files": getattr(r, "infected_files", None),
        "globals": globs,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
