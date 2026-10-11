"""Minimal Hugging Face helpers: dataset metadata + parquet download (stdlib + pyarrow + certifi).

Downloaded files are untrusted data. They are only parsed with pyarrow, never executed.
"""
import json
import os
import ssl
import sys
import urllib.request

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover
    _CTX = ssl.create_default_context()

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
API = "https://huggingface.co/api/datasets/"


def get_json(url):
    with urllib.request.urlopen(url, timeout=60, context=_CTX) as r:
        return json.load(r)


def info(ds):
    """-> {"id", "license", "gated", "url"} from the HF API (verifies the dataset exists)."""
    j = get_json(API + ds)
    lic = [t.split(":", 1)[1] for t in j.get("tags", []) if t.startswith("license:")]
    return {"id": ds, "license": ",".join(lic) or "unspecified", "gated": j.get("gated"),
            "url": "https://huggingface.co/datasets/" + ds, "sha": j.get("sha")}


def parquet(ds, split, config="default", shard=0):
    """Download one parquet shard to data/<ds>/<config>-<split>-<shard>.parquet (cached) and return the path."""
    out_dir = os.path.join(DATA, ds.replace("/", "__"))
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{config}-{split}-{shard}.parquet")
    if not os.path.exists(path):
        url = f"{API}{ds}/parquet/{config}/{split}/{shard}.parquet"
        tmp = path + ".part"
        with urllib.request.urlopen(url, timeout=300, context=_CTX) as r, open(tmp, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        os.replace(tmp, path)
    return path


def read(path, columns=None, limit=None):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    rows = []
    for batch in pf.iter_batches(batch_size=2048, columns=columns):
        rows.extend(batch.to_pylist())
        if limit and len(rows) >= limit:
            break
    return rows[:limit] if limit else rows


def schema(path):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    return pf.metadata.num_rows, [(f.name, str(f.type)[:80]) for f in pf.schema_arrow]


if __name__ == "__main__":
    # usage: python -I hf.py <dataset> <split> [config]  -> prints license, row count and column names/types only
    ds, split = sys.argv[1], sys.argv[2]
    cfg = sys.argv[3] if len(sys.argv) > 3 else "default"
    print(info(ds))
    n, cols = schema(parquet(ds, split, cfg))
    print(n, cols)
