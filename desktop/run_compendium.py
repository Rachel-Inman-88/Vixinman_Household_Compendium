"""Compendium Desktop launcher.

Starts Compendium as a little local web server and opens it in the default
browser, so a teammate can run the whole app by double-clicking one file.
Their data (the database + uploaded files) is kept in a personal "Compendium"
folder under their home directory, separate from the program itself, so it
survives replacing the app with a newer build.

This file is the entry point PyInstaller bundles into Compendium.exe; it also
runs directly with `python desktop/run_compendium.py` for testing.

If anything goes wrong at startup, the error is written to
<home>/Compendium/compendium-startup-error.log AND the window is kept open, so a
crash never just "flashes and vanishes."
"""

import os
import shutil
import socket
import sys
import threading
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

# Each person gets their own copy of the data here. Chosen BEFORE importing
# app, because app reads COMPENDIUM_DATA_DIR at import time.
DATA_DIR = Path.home() / "Compendium"
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("COMPENDIUM_DATA_DIR", str(DATA_DIR))

# Where Compendium.exe (or this launcher, when run from source) actually lives.
# Used to look for a first-run import folder sitting next to the program.
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent


def _db_is_empty_starter(path):
    """True if `path` is a brand-new database with nothing worth keeping — no
    clients, no jobs, and no employees with a login. A blank starter DB (which
    an earlier launch may have already created) must not block importing real
    data. Anything unreadable is treated as NOT empty, so we never clobber a
    database we can't inspect."""
    import sqlite3
    try:
        con = sqlite3.connect(str(path))
        try:
            for table, cond in (("clients", ""), ("jobs", ""),
                                ("employees",
                                 " WHERE COALESCE(username,'') != ''"
                                 " AND COALESCE(password_hash,'') != ''")):
                try:
                    n = con.execute(
                        f"SELECT COUNT(*) FROM {table}{cond}").fetchone()[0]
                except sqlite3.Error:
                    n = 0  # table not created yet -> nothing there
                if n:
                    return False
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _seed_from_import():
    """Copy an existing job_creator.db (+ uploads) into the personal ~/Compendium
    folder, so someone moving from the web/dev version keeps all their data.

    It looks, in order, at:
      1. $COMPENDIUM_IMPORT           - a folder or a .db file you point it at
      2. <next to Compendium.exe>/Compendium-Import/
      3. <next to Compendium.exe>/job_creator.db
      4. ~/Downloads/Compendium-Import/

    A folder may contain job_creator.db and an uploads/ folder. The import runs
    when ~/Compendium has no database yet, OR when the one there is a blank starter
    (no clients/jobs/logins) that an earlier launch created. A database with
    real data in it is never touched.
    """
    target_db = DATA_DIR / "job_creator.db"
    if target_db.exists() and not _db_is_empty_starter(target_db):
        return  # real data already here — never clobber it

    # Resolve the source db (and, if present, the uploads folder beside it).
    candidates = []
    env = os.environ.get("COMPENDIUM_IMPORT", "").strip()
    if env:
        candidates.append(Path(env))
    candidates += [
        APP_DIR / "Compendium-Import",
        APP_DIR / "job_creator.db",
        Path.home() / "Downloads" / "Compendium-Import",
    ]

    src_db = None
    src_uploads = None
    for cand in candidates:
        try:
            if cand.is_file() and cand.suffix == ".db":
                src_db = cand
                src_uploads = cand.parent / "uploads"
                break
            if cand.is_dir() and (cand / "job_creator.db").is_file():
                src_db = cand / "job_creator.db"
                src_uploads = cand / "uploads"
                break
        except OSError:
            continue

    if not src_db:
        return  # nothing to import — normal fresh start

    # If a blank starter DB is already here, set it aside before importing so
    # nothing is ever destroyed outright.
    if target_db.exists():
        backup = target_db.with_name(
            f"job_creator.db.replaced-{datetime.now():%Y%m%d-%H%M%S}")
        try:
            os.replace(target_db, backup)
        except OSError:
            pass

    shutil.copy2(src_db, target_db)
    imported = f"database from {src_db}"
    if src_uploads and src_uploads.is_dir():
        dest_uploads = DATA_DIR / "uploads"
        if not dest_uploads.exists():
            shutil.copytree(src_uploads, dest_uploads)
            imported += " + uploaded files"

    log = DATA_DIR / "compendium-import.log"
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  imported {imported}\n")
    except OSError:
        pass
    print("  Imported your existing " + imported)
    print("  (this happens only once — future launches use ~/Compendium)")


def _install_error_logging(app):
    """A packaged app runs with debug=False, so a server error (HTTP 500)
    normally leaves only a scrolled-past line in the console. Capture the full
    traceback of any unhandled error to <home>/Compendium/compendium-error.log and show
    a plain-English page that says where to find it, so a crash on someone
    else's machine can actually be diagnosed."""
    import logging
    from flask import request
    from werkzeug.exceptions import HTTPException

    log_path = DATA_DIR / "compendium-error.log"
    try:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)s  %(message)s"))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
    except OSError:
        pass  # never let logging setup stop the app from starting

    @app.errorhandler(Exception)
    def _log_unhandled(e):
        # Real HTTP responses (404, 405, redirects raised as exceptions, …)
        # should pass through untouched — only true server errors are logged.
        if isinstance(e, HTTPException):
            return e
        try:
            where = request.method + " " + request.path
        except Exception:
            where = "?"
        app.logger.error("Unhandled error on %s\n%s", where, traceback.format_exc())
        return (
            "<html><body style=\"font-family:system-ui,Segoe UI,sans-serif;"
            "max-width:640px;margin:3rem auto;padding:0 1rem;color:#1f2937;\">"
            "<h1 style=\"color:#9a1c1c;\">Compendium hit a snag</h1>"
            "<p>Something went wrong loading that page. Your data is safe.</p>"
            "<p>A detailed error report was just saved to:</p>"
            f"<p style=\"font-family:monospace;background:#f1f5f9;padding:.6rem;"
            f"border-radius:6px;word-break:break-all;\">{log_path}</p>"
            "<p>Please send that file to whoever set up Compendium — it says "
            "exactly what to fix. Then try again.</p>"
            "</body></html>", 500)


def _free_port():
    """Grab an available localhost port so two copies (or another program
    on 5000) never collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    # Imported here (not at module top) so that a failure to load the app —
    # e.g. a missing bundled file or system library — is caught and reported
    # by the handler below instead of crashing before it can run.
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import app, init_db

    # Capture any server error to a log file with a friendly page (must be set
    # up before the first request is served).
    _install_error_logging(app)

    # First launch only: bring over an existing job_creator.db + uploads if the
    # person dropped them next to the exe (see _seed_from_import). init_db()
    # then migrates the copied database up to the current schema.
    _seed_from_import()
    init_db()
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    print("=" * 60)
    print("  Compendium is starting up...")
    print(f"  It will open in your web browser at:  {url}")
    print("  Your data is saved in:  " + str(DATA_DIR))
    print()
    print("  KEEP THIS WINDOW OPEN while you use Compendium.")
    print("  Close this window to shut Compendium down.")
    print("=" * 60)
    # Open the browser a moment after the server starts listening.
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # debug=False: no reloader (which would fail inside a frozen exe) and no
    # debugger. threaded=True so the browser and app can talk concurrently.
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


def _report_crash():
    """Persist the traceback and hold the window open so the error is
    readable even when Compendium was started by double-clicking."""
    tb = traceback.format_exc()
    log = DATA_DIR / "compendium-startup-error.log"
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{tb}\n")
    except Exception:
        pass
    print("\n" + "=" * 60)
    print("  Compendium could not start. What went wrong:")
    print("=" * 60)
    print(tb)
    print(f"  A copy of this was saved to:\n    {log}")
    print("  Send that file to whoever is helping you set up Compendium.")
    print("=" * 60)
    try:
        input("\n  Press Enter to close this window... ")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        _report_crash()
        sys.exit(1)
