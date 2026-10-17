#!/usr/bin/env python3
"""Archive daily HTML reports to Google Drive as native Google Docs.

Uploads each HTML report to the Drive Reports folder, converts to a native
Google Doc (via files.copy with Docs MIME type), then trashes the HTML
intermediate. Per Ceos's rule: guides/reports are native Google Docs.

Usage:
    python3 src/archive_to_drive.py --reports docs/reports/daily-watchlist-2026-10-17.html
    python3 src/archive_to_drive.py --reports docs/reports/*.html --folder 1SPQHPXrITBsAu543aDrWtJ73mbDN-gph

Requires: hatch_gws_cli with Drive connected.
Stdlib-only.
"""

import argparse
import json
import os
import subprocess
import sys

# Default: Trading System > Reports folder
DEFAULT_FOLDER = "1SPQHPXrITBsAu543aDrWtJ73mbDN-gph"
DOCS_MIME = "application/vnd.google-apps.document"


def run_cli(*args):
    """Run hatch_gws_cli and return parsed JSON output."""
    cmd = ["/opt/hatch/bin/hatch_gws_cli"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"CLI error: {result.stderr}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"raw": result.stdout}


def archive_report(html_path, folder_id):
    """Upload HTML, convert to Google Doc, trash the intermediate."""
    name = os.path.basename(html_path).replace(".html", "")
    abs_path = os.path.abspath(html_path)

    if not os.path.exists(abs_path):
        print(f"  SKIP: not found: {html_path}")
        return None

    print(f"  Uploading {name}...")

    # Step 1: Upload HTML to the Reports folder
    upload = run_cli(
        "drive", "files", "create",
        "--params", json.dumps({"name": f"{name}.html"}),
        "--json", json.dumps({"name": f"{name}.html", "parents": [folder_id]}),
        "--upload", abs_path,
    )
    if not upload or "id" not in upload:
        print(f"  FAILED upload: {name}")
        return None

    html_id = upload["id"]
    print(f"  Uploaded (id={html_id}), converting to Doc...")

    # Step 2: Convert to native Google Doc via files.copy
    doc = run_cli(
        "drive", "files", "copy",
        "--params", json.dumps({"fileId": html_id}),
        "--json", json.dumps({
            "name": name,
            "mimeType": DOCS_MIME,
            "parents": [folder_id],
        }),
    )
    if not doc or "id" not in doc:
        print(f"  FAILED convert: {name}")
        return None

    doc_id = doc["id"]
    print(f"  Converted (doc id={doc_id})")

    # Step 3: Trash the HTML intermediate
    run_cli(
        "drive", "files", "update",
        "--params", json.dumps({"fileId": html_id}),
        "--json", json.dumps({"trashed": True}),
    )
    print(f"  Trashed HTML intermediate")

    link = doc.get("webViewLink", f"https://docs.google.com/document/d/{doc_id}/edit")
    print(f"  Done: {link}")
    return doc_id


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reports", nargs="+", required=True,
                        help="HTML report files to archive")
    parser.add_argument("--folder", default=DEFAULT_FOLDER,
                        help="Drive folder ID for archived reports")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be archived without doing it")
    args = parser.parse_args()

    if args.dry_run:
        print("Would archive:")
        for r in args.reports:
            print(f"  {r} -> Drive folder {args.folder}")
        return 0

    # Check Drive connection
    status = run_cli("drive", "status")
    if not status:
        print("ERROR: Cannot reach Google Drive", file=sys.stderr)
        return 1

    archived = 0
    for report in args.reports:
        # Expand globs
        import glob
        for path in sorted(glob.glob(report)) if "*" in report else [report]:
            doc_id = archive_report(path, args.folder)
            if doc_id:
                archived += 1

    print(f"\nArchived {archived} report(s) to Drive as native Google Docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
