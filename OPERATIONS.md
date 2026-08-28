# Operating the Compendium

A reference for running, updating, and troubleshooting the app across its
two homes — the household's own LAN machine and the always-on VPS — and
how the pieces between them actually connect. Written as a companion to
`DEPLOY.md` (which walks through the one-time VPS setup) and `README.md`
(which lists what the app does); this doc is about keeping it running
afterward.

---

## 1. The big picture

There are **two separate running copies of this app**, and **two
separate databases** — they do not sync with each other automatically.

```
                     GitHub (source of truth)
                     Rachel-Inman-88/Vixinman_Household_Compendium
                    /                                    \
             branch: main                    branch: deploy/production-
                  |                                hosting-security
                  v                                        v
          LAN machine (Windows)                    VPS (DigitalOcean)
          python app.py, port 5000          Caddy :443 -> gunicorn :8000
          reachable on home WiFi only            reachable from anywhere
                  |                                        |
          job_creator.db (local file)         job_creator.db (own file,
                                                  under /opt/compendium)
```

**Important:** as of this writing, both the LAN checkout and the VPS
happen to be on the `deploy/production-hosting-security` branch — that's
incidental to when this was set up, not a permanent rule. Always check
with `git branch --show-current` rather than assuming; branches will get
merged and re-organized over time as more pieces land on `main`.

**The two databases are independent.** A task added on the VPS site
doesn't appear on the LAN copy, and vice versa. Pick one as your real,
day-to-day source of truth (the VPS, since that's the one reachable
throughout the day) and treat the LAN copy purely as a fallback for when
the VPS is unreachable — not as a second place data casually gets
entered. If both ever get used for real work in the same week, they will
diverge, and there's no built-in merge tool to reconcile that.

As of Piece 70, a scheduled task pulls a fresh copy of the VPS's nightly
backup down to this LAN machine automatically every morning (Section 5
below) — that keeps the LAN's backup copy current without any manual
effort, but it is still **one-way and non-live**: a snapshot from
sometime in the last day, not a real-time mirror.

### The VPS request path, step by step

1. A browser requests `https://home.jstellarcomp.com`.
2. DNS (managed at Namecheap) resolves that name to the VPS's IP address.
3. **Caddy** (listening on ports 80/443) receives the request, handles
   HTTPS (a Let's Encrypt certificate it obtained and renews itself,
   with zero manual steps), and forwards the request internally.
4. **gunicorn** (listening only on `127.0.0.1:8000`, unreachable from the
   internet directly) receives that forwarded request and runs it
   through the actual Flask app (`app.py`).
5. The app reads/writes `job_creator.db` (SQLite) on disk.

Two things wrap around this whole chain: **systemd** keeps gunicorn
running (restarts it if it crashes, starts it on boot) under the
`compendium` service account, and **ufw** (the firewall) blocks every
port except SSH/80/443 from being reachable at all.

### The LAN request path, step by step

1. A device on the home WiFi requests `http://<this-computer's-LAN-IP>:5000`.
2. `python app.py` (with `COMPENDIUM_HOST=0.0.0.0` set) answers directly —
   no Caddy, no gunicorn, no systemd. It's just the plain Flask
   development server, which is why this path only works while someone
   has it open and running, and only reaches devices on the same WiFi.

---

## 2. Updating the software

### On the VPS

```bash
ssh root@<the droplet's IP address>
cd /opt/compendium
sudo -u compendium git pull
sudo -u compendium /opt/compendium/venv/bin/pip install -r requirements.txt -r requirements-server.txt
sudo systemctl restart compendium
sudo systemctl status compendium --no-pager -l
```

Look for `Active: active (running)` at the end, same as during setup.

**`git pull` may ask for your GitHub username and token again**, the
same way the original clone did — this repo has no saved credential on
the server yet. Keep your Personal Access Token handy (or generate a new
one if it's expired — GitHub → Settings → Developer settings → Personal
access tokens).

**If the update includes a change to `deploy/compendium.service` or
`deploy/Caddyfile`**, pulling the new code is *not* enough on its own —
those two files only take effect once actually copied to their real
locations and reloaded:

```bash
sudo cp /opt/compendium/deploy/compendium.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart compendium

sudo cp /opt/compendium/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

(This is exactly what we hit live during setup — a fix to
`compendium.service` sat in the repo but had no effect until manually
re-copied. Worth remembering any time a future piece touches either
file.)

### On the LAN machine

The LAN copy is whatever's checked out in this same folder. To update it:

```bash
git pull
```

Then restart however it's currently running — stop the existing
`python app.py` window (Ctrl+C) and start it again:

```bash
python app.py
```

or, to let a phone on the same WiFi reach it:

```bash
set COMPENDIUM_HOST=0.0.0.0
python app.py
```

(PowerShell: `$env:COMPENDIUM_HOST = "0.0.0.0"` instead of `set`.)

---

## 3. Running the LAN server (day to day)

1. Open a terminal in this folder.
2. `python app.py` (or with `COMPENDIUM_HOST=0.0.0.0` for phone access,
   as above).
3. Browse to `http://localhost:5000` (or the LAN IP, for a phone).
4. `Ctrl+C` in that terminal to stop it.

No systemd equivalent exists here — if the terminal window closes, the
server stops. That's expected; this path is the backup, not the
always-on one.

---

## 4. VPS file & system glossary

| Path / thing | What it is |
|---|---|
| `/opt/compendium/` | The app's git checkout on the server — same repo, same files as the LAN copy |
| `/opt/compendium/venv/` | An isolated Python environment just for this app |
| `/opt/compendium/.env` | Secrets/config: `COMPENDIUM_SECRET_KEY`, `COMPENDIUM_BEHIND_PROXY`, `COMPENDIUM_DATA_DIR`. Mode `600`, owned by `compendium` — nobody else on the server can read it |
| `/opt/compendium/job_creator.db` | The VPS's own database — separate from the LAN copy, see Section 1 |
| `/opt/compendium/backups/` | Nightly SQLite snapshots, most recent 14 kept |
| `/etc/systemd/system/compendium.service` | The **live** service definition systemd actually reads — a *copy* of `deploy/compendium.service`, not a live link to it |
| `/etc/caddy/Caddyfile` | The **live** Caddy config — a *copy* of `deploy/Caddyfile`, same caveat |
| `compendium`'s crontab | The nightly backup schedule — lives in the system's cron subsystem, not in git at all. View it with `sudo crontab -u compendium -l` |
| the `compendium` user | A dedicated, low-privilege system account the app runs as — not `root` |

---

## 5. Automatic LAN backup of VPS data (Piece 70)

A scheduled task on the LAN machine (`CompendiumVPSBackupPull`, Windows
Task Scheduler, daily at 6:00 AM) runs `deploy/pull_vps_backup.py`,
which fetches the VPS's **latest already-made nightly snapshot** (the
one `backup_db.py` produces via SQLite's online backup API — never the
live database file directly, since that could be mid-write) down to
this machine's `lan_backups/` folder. One direction only: VPS → LAN,
never the reverse, and it never touches the LAN's own live
`job_creator.db`.

```bash
# Run it by hand anytime:
python deploy/pull_vps_backup.py --host root@143.198.155.113 --keep 14

# Check/trigger the scheduled task:
schtasks /query /tn "CompendiumVPSBackupPull" /v /fo list
schtasks /run /tn "CompendiumVPSBackupPull"
```

`Last Result` should read `0` (success). `267009` isn't an error — it's
Task Scheduler's own "still running, check again in a few seconds" code.

**A real, hard-won gotcha:** the scheduled task cannot run the script
directly from inside this repo's folder, because this repo lives under
**OneDrive**, and something about how OneDrive interacts with a
background/non-interactive process caused every attempt to fail with
`Access is denied` (`-2147024891` / `0x80070005`) — even though running
the exact same script by hand, interactively, always worked fine. The
working fix: a **plain copy** of the script lives outside OneDrive
entirely, at `C:\CompendiumOps\pull_vps_backup.py`, launched by
`C:\CompendiumOps\run_pull_vps_backup.bat` — that's what the scheduled
task actually points at. It's told where to put backups via
`--local-dir`, so the pulled files still land in this repo's
`lan_backups/` folder as normal.

**If `deploy/pull_vps_backup.py` is ever edited in the repo**, the copy
at `C:\CompendiumOps\pull_vps_backup.py` needs to be manually refreshed
to match — it will not update on its own:

```bash
cp "path\to\this\repo\deploy\pull_vps_backup.py" C:\CompendiumOps\pull_vps_backup.py
```

---

## 6. Troubleshooting playbook

**Site is unreachable entirely (nothing loads, not even an error page)**
```bash
sudo systemctl status compendium --no-pager -l
sudo systemctl status caddy --no-pager -l
```
Whichever one isn't `active (running)` is the problem. Get its recent
logs with `sudo journalctl -u compendium -n 50 --no-pager` (swap in
`caddy` for the other service) and read the last few lines for the
actual error.

**Browser shows a "502 Bad Gateway" from Caddy specifically**
Caddy itself is fine — it's gunicorn/the app behind it that's down or
crashing. Check `compendium`'s status/logs as above.

**Just made a config change and it doesn't seem to have taken effect**
Check whether the file you edited was `deploy/compendium.service` or
`deploy/Caddyfile` *inside the repo* — those need the copy + reload
commands from Section 2 above. Editing the repo copy alone changes
nothing live.

**A command that should print nothing instead shows an error**
Read it — most of these commands (`cp`, `chown`, `chmod`, `mkdir`)
succeed silently and only print on failure. A "No such file or
directory" error usually means an earlier step (very often a `nano`
edit) didn't actually save. Verify with `ls -la <path>` before assuming
the current command is the one at fault.

**`nano` — the save/exit sequence that actually works**
Press **Ctrl+O**, then **Enter** to confirm the filename, *then*
**Ctrl+X** to exit. Doing Ctrl+X first and answering anything but "Y" to
its save prompt discards the whole edit.

**SSH connection drops mid-command ("Connection reset")**
Just reconnect (`ssh root@<ip>` again) and check whether the command
actually finished before the connection died —
`sudo systemctl status <service>` or `ps aux | grep <name>` from the
fresh connection, rather than assuming it failed and blindly re-running
it (re-running a completed `apt install` is harmless, but re-running
something like a database migration blindly is a habit worth avoiding).

**A systemd unit name "could not be found"**
Unit names are case-sensitive — `compendium.service`, not
`Compendium.service`. Retype or re-paste exactly.

**A fresh gunicorn install logs `[ERROR] Control server error: ...
'/nonexistent'`**
Already fixed in this repo's `deploy/compendium.service`
(`Environment=HOME=/opt/compendium`) — this is only a concern if
rebuilding that file from scratch. Root cause: `adduser --system`
without `--home` gives the account a literal, nonexistent home
directory, and gunicorn tries to use `$HOME` as scratch space.

**Caddy logs `no valid A records found for <domain>`**
The domain in `deploy/Caddyfile` doesn't match what your DNS actually
points to. Check Namecheap's Advanced DNS tab — the Host field must be
exactly `@` for the bare domain (e.g. `jstellarcomp.com`) or the
specific subdomain you're using (e.g. `home` for
`home.jstellarcomp.com`) — and confirm which one the Caddyfile is
actually configured for.

**Can't log in — "Too many failed attempts, try again in 15 minutes"**
This is the login rate-limiter working as designed (8 failed attempts
per IP address within 15 minutes), not a bug. Wait it out, or double
check the password if it keeps happening.

**`schtasks /create` fails with "Invalid argument/option"**
`schtasks.exe` can't reliably handle two separate quoted paths
back-to-back in one `/tr` value (e.g. a quoted `python.exe` path
immediately followed by a quoted script path that also has spaces in
it). Fix: put the real command inside a small `.bat` file instead
(`cmd.exe` parses nested quotes fine at run time), and point `/tr` at
that one single, simply-quoted `.bat` path.

**A scheduled task's `Last Result` is `-2147024891` (`0x80070005`,
"Access is denied")**
If the task's target script lives inside a **OneDrive-synced** folder,
that's the likely cause — a background/non-interactive process can fail
to read files there even though the exact same script runs fine
interactively. Fix: keep a plain copy of whatever the task launches
outside OneDrive entirely (see Section 5's `C:\CompendiumOps\` example)
rather than trying to fix OneDrive's side of it.

**A scheduled task's `Last Result` is `267009`**
Not an error — Task Scheduler's own status code for "the task is
currently running." Wait a few seconds and query again.

**Checking the firewall**
```bash
sudo ufw status
```
Should list `22/tcp` (or `OpenSSH`), `80/tcp`, and `443/tcp` as `ALLOW` —
nothing else needs to be open.

**Checking backups exist**
```bash
ls -l /opt/compendium/backups
sudo crontab -u compendium -l
```
First confirms real files are there; second confirms the nightly job is
still scheduled.

---

## 7. Recurring things to remember

- **Domain renewal** — Namecheap bills yearly; they'll email ahead of
  renewal. Losing the domain would break `home.jstellarcomp.com` even
  though the server itself is fine.
- **VPS billing** — DigitalOcean bills monthly against the card on file.
- **HTTPS certificate renewal** — fully automatic via Caddy; nothing to
  do here, ever, as long as the server and DNS stay as they are.
- **Off-box backup copies** — as of Piece 70, this is automated: the
  `CompendiumVPSBackupPull` scheduled task pulls the VPS's latest
  snapshot down to this LAN machine's `lan_backups/` folder every
  morning at 6am. Worth occasionally glancing at Task Scheduler to
  confirm it's still running (`Last Result: 0`) — a silently-broken
  scheduled task is easy to not notice for months.

---

## 8. Quick command reference

```bash
# Is it running?
sudo systemctl status compendium --no-pager -l
sudo systemctl status caddy --no-pager -l

# Recent logs
sudo journalctl -u compendium -n 50 --no-pager
sudo journalctl -u caddy -n 50 --no-pager

# Restart after a change
sudo systemctl restart compendium
sudo systemctl reload caddy      # reload, not restart -- keeps existing connections alive

# Update the code
cd /opt/compendium && sudo -u compendium git pull

# Firewall / VPS-side backups
sudo ufw status
sudo crontab -u compendium -l
ls -l /opt/compendium/backups

# LAN-side backup pull (Windows)
schtasks /query /tn "CompendiumVPSBackupPull" /v /fo list
schtasks /run /tn "CompendiumVPSBackupPull"
```
