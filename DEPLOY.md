# Deploying the Compendium to a VPS

This covers running the app on a small VPS (Ubuntu/Debian assumed) so
it's reachable throughout the day, with the local/LAN setup (see
`README.md`'s "Running on the home network" section) kept as a backup.

**Out of scope here:** buying/provisioning the VPS itself, paying for
it, and registering/pointing a domain's DNS at it. Those are your own
steps — this doc starts once you're SSH'd into a freshly provisioned
box with a domain name ready to point at it.

## 1. Basic server setup

```bash
sudo apt update && sudo apt upgrade -y
sudo adduser --system --group compendium
sudo mkdir -p /opt/compendium
sudo chown compendium:compendium /opt/compendium
```

Copy the repo to `/opt/compendium` (e.g. `git clone` your fork, or
`scp` a tarball), then as the `compendium` user (or via `sudo -u
compendium`):

```bash
cd /opt/compendium
python3 -m venv venv
venv/bin/pip install -r requirements.txt -r requirements-server.txt
```

## 2. Secret key and environment file

Generate a real secret key once:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Create `/opt/compendium/.env` (owned by `compendium`, mode `600` — it
holds a secret):

```
COMPENDIUM_SECRET_KEY=<the value you just generated>
COMPENDIUM_BEHIND_PROXY=1
COMPENDIUM_DATA_DIR=/opt/compendium
```

```bash
sudo chown compendium:compendium /opt/compendium/.env
sudo chmod 600 /opt/compendium/.env
```

Since `/opt/compendium` is the git checkout itself, naming this file
`.env` (rather than something like `compendium.env`) matters: the
repo's `.gitignore` already has an exact-match `.env` entry, so it
won't get swept up by an accidental `git add -A` on the server.
`COMPENDIUM_BEHIND_PROXY` must only be set here, on the VPS behind
Caddy — never on the LAN setup, since it tells the app to trust
`X-Forwarded-For`/`X-Forwarded-Proto` headers, which is only safe with
a real reverse proxy in front.

## 3. systemd service

```bash
sudo cp deploy/compendium.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now compendium
sudo systemctl status compendium
```

The database and `secret_key.txt` (used only as a fallback if
`COMPENDIUM_SECRET_KEY` isn't set — it is here, but the file still
gets created harmlessly) will appear under `/opt/compendium` on first
start. Watch the boot log for errors:

```bash
sudo journalctl -u compendium -f
```

## 4. Caddy (reverse proxy + automatic HTTPS)

```bash
sudo apt install -y caddy
```

Edit `deploy/Caddyfile`, replacing `yourdomain.com` with your real
domain, then:

```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy will automatically request and renew a Let's Encrypt certificate
for the domain the first time it starts — this only works once DNS
for that domain already points at the VPS's IP address.

## 5. Firewall

Only SSH, HTTP, and HTTPS need to be reachable from the internet — the
app itself listens on `127.0.0.1:8000`, not a public interface:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 6. Backups

Test it once by hand:

```bash
venv/bin/python deploy/backup_db.py --data-dir /opt/compendium --keep 14
```

Then schedule it daily via cron (as the `compendium` user):

```bash
crontab -e
# add:
0 3 * * * /opt/compendium/venv/bin/python /opt/compendium/deploy/backup_db.py --data-dir /opt/compendium --keep 14
```

This only writes snapshots to `/opt/compendium/backups` on the same
disk — it does not protect against the VPS itself failing. Also copy
the newest snapshot off-box on some schedule (`rsync`, `rclone` to
cloud storage, or plain `scp` to another machine you own) — whichever
fits how you want backups stored is your call; this isn't wired up
automatically.

## 7. Known limitation: no CSRF tokens

This app doesn't have CSRF token protection on its forms (a genuine
gap, flagged rather than silently left — retrofitting it across the
app's many POST forms is a separate, larger piece of work).
`SESSION_COOKIE_SAMESITE=Lax` is set as a partial mitigation (it stops
the session cookie from riding along on most cross-site requests in
modern browsers) but isn't a full replacement for real CSRF tokens.
Worth keeping in mind if this is ever opened up beyond household use.

## Updating after this initial setup

```bash
cd /opt/compendium
git pull
venv/bin/pip install -r requirements.txt -r requirements-server.txt
sudo systemctl restart compendium
```
