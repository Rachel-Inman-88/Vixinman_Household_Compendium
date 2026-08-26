"""Piece 69: SQLite backup for the Compendium's production database.

Uses sqlite3's online backup API (Connection.backup), not a raw file
copy -- a file copy can snapshot the database mid-write and produce a
corrupt backup; the backup API is safe to run while the app is live.

Usage (on the VPS, via cron):
    python3 backup_db.py --data-dir /opt/compendium --keep 14

Writes timestamped snapshots into <data-dir>/backups/ and deletes any
beyond the most recent --keep. This only protects against mistakes in
the running database (bad data, accidental deletes) -- it does NOT
protect against the VPS's own disk failing, since everything still
lives on one machine. Also copy the newest snapshot off-box on a
schedule (rsync/rclone/scp to another host or cloud storage); which
tool fits best depends on where the household wants backups to land,
so that step isn't automated here.
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def backup(data_dir: Path, keep: int) -> Path:
    src_path = data_dir / "job_creator.db"
    if not src_path.exists():
        sys.exit(f"No database found at {src_path}")

    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_path = backups_dir / f"job_creator-{stamp}.db"

    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()

    existing = sorted(backups_dir.glob("job_creator-*.db"))
    for old in existing[:-keep] if keep > 0 else []:
        old.unlink()

    return dest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path,
                         help="Directory holding job_creator.db (same as COMPENDIUM_DATA_DIR)")
    parser.add_argument("--keep", type=int, default=14,
                         help="Number of recent snapshots to retain (default 14)")
    args = parser.parse_args()

    snapshot = backup(args.data_dir, args.keep)
    print(f"Backed up to {snapshot}")
