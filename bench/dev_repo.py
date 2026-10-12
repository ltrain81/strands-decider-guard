"""Negatives from this repository's own source code: code *about* personal data (field names, category descriptions,
validation logic) but containing none. The live guard blocked edits to guard_core.py as "personal contact", so this
set guards against that kind of false positive. Test fixtures, sample data, templates and docs are excluded.

Writes data/sets/dev_repo.jsonl (1,500-character segments). Prints counts only.

Run:  .venv/bin/python -I dev_repo.py
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SETS = os.path.join(HERE, "data", "sets")
INCLUDE = ["guard/*.py", "client/*.py", "admin/api/*.py", "admin/dev_server.py", "admin/web/app.js", "admin/web/charts.js",
           "admin/web/i18n.js", "cdk/lib/*.ts", "scripts/*.sh", "*.sh", "litellm/*.py",
           "bench/run.py", "bench/tune.py", "bench/features.py", "bench/compare.py", "bench/report.py", "bench/perf.py"]
SEGMENT = 1500


def main():
    out = []
    for pattern in INCLUDE:
        for path in sorted(glob.glob(os.path.join(REPO, pattern))):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            rel = os.path.relpath(path, REPO)
            for i in range(0, len(text), SEGMENT):
                seg = text[i:i + SEGMENT]
                if len(seg.strip()) > 100:
                    out.append({"id": f"dev_repo-{rel}-{i // SEGMENT}", "set": "dev_repo", "lang": "en", "label": 0,
                                "cats": [], "group": "neg", "kind": None, "text": seg})
    with open(os.path.join(SETS, "dev_repo.jsonl"), "w") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"dev_repo: {len(out)} segments from {len({r['id'].rsplit('-', 1)[0] for r in out})} files")


if __name__ == "__main__":
    main()
