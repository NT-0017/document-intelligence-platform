"""Send the sample dataset to a running API and save every JSON response in sample_outputs/.

Usage:
    python scripts/run_samples.py "path/to/New Dataset" [--base-url http://localhost:8000] [--limit 3]

Expects the dataset layout: Invoices/, Balance Sheet/, Profit & Loss/, Cash Flows/.
Also sends one unsupported file so the error response is captured.
"""
import argparse
import json
import mimetypes
import pathlib
import re
import sys
import time

import httpx

FOLDERS = {
    "Invoices": "invoice",
    "Balance Sheet": "balance_sheet",
    "Profit & Loss": "profit_and_loss",
    "Cash Flows": "cash_flow_statement",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--limit", type=int, default=3, help="files per folder (free-tier LLM limits are small)")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "sample_outputs"))
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(exist_ok=True)

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        for folder, doc_type in FOLDERS.items():
            files = sorted(p for p in (pathlib.Path(args.dataset) / folder).glob("*") if p.is_file())[: args.limit]
            for path in files:
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                with path.open("rb") as fh:
                    r = client.post("/api/v1/documents/process", data={"document_type": doc_type},
                                    files={"file": (path.name, fh, mime)})
                target = out / (re.sub(r"[^A-Za-z0-9._-]+", "_", f"{doc_type}__{path.stem}") + ".json")
                target.write_text(json.dumps(r.json(), indent=2, ensure_ascii=False))
                print(f"{r.status_code}  {doc_type:22} {path.name}  -> {target.name}")
                time.sleep(4)  # stay under free-tier rate limits

        bad = client.post("/api/v1/documents/process", data={"document_type": "invoice"},
                          files={"file": ("not_a_document.txt", b"hello", "text/plain")})
        (out / "error__unsupported_file.json").write_text(json.dumps(bad.json(), indent=2))
        print(f"{bad.status_code}  unsupported file -> error__unsupported_file.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
