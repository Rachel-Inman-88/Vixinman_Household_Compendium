"""Piece 70: one-way backup pull -- fetches the VPS's latest nightly
snapshot (produced by backup_db.py's SQLite online-backup-API, already
safe to copy since it's a finished, consistent file) down to this LAN
machine.

One direction only, by design: VPS -> LAN, never the reverse. This never
touches the LAN's own live job_creator.db and never pushes anything back
up -- the VPS stays the single source of truth for daily use; the LAN
side is purely a backup destination, not a second live copy.

Usage (from this repo's own folder, on the LAN machine):
    python deploy/pull_vps_backup.py --host root@<vps-ip-or-domain> --keep 14

Runs equally well from anywhere else on disk -- pass --local-dir to
control where snapshots land (default: a "lan_backups" folder next to
wherever this script itself lives).

Requires an OpenSSH client (ssh/scp) on PATH and the same SSH key used
to reach the VPS during setup.
"""
import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_LOCAL_BACKUP_DIR = Path(__file__).resolve().parent.parent / "lan_backups"


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout


def latest_remote_backup(host, remote_dir):
    out = run(["ssh", host, f"ls -1 {remote_dir}"])
    files = sorted(f for f in out.splitlines() if f.startswith("job_creator-") and f.endswith(".db"))
    if not files:
        sys.exit(f"No backup files found in {remote_dir} on {host}")
    return files[-1]


def pull(host, remote_dir, keep, local_dir):
    local_dir.mkdir(parents=True, exist_ok=True)
    newest = latest_remote_backup(host, remote_dir)
    dest = local_dir / newest

    if dest.exists():
        print(f"Already have {newest} -- nothing new to pull.")
    else:
        run(["scp", f"{host}:{remote_dir}/{newest}", str(dest)])
        print(f"Pulled {newest} -> {dest}")

    existing = sorted(local_dir.glob("job_creator-*.db"))
    for old in (existing[:-keep] if keep > 0 else []):
        old.unlink()
        print(f"Removed old local backup: {old.name}")

    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True,
                         help="SSH destination for the VPS, e.g. root@143.198.155.113")
    parser.add_argument("--remote-dir", default="/opt/compendium/backups",
                         help="Directory on the VPS holding backup_db.py's snapshots")
    parser.add_argument("--keep", type=int, default=14,
                         help="Number of recent snapshots to retain locally (default 14)")
    parser.add_argument("--local-dir", type=Path, default=DEFAULT_LOCAL_BACKUP_DIR,
                         help="Where to store pulled backups (default: lan_backups next to this script)")
    args = parser.parse_args()

    pull(args.host, args.remote_dir, args.keep, args.local_dir)
