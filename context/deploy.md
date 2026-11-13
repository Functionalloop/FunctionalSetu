# Deploy: server, Docker Compose, Caddy, backups, APK

Current state (13 Nov): branch `step6-server`. Stack running at `https://myjansetu.com` with the real roll since 6.5 (31,871 voters, workspace `naik`, 4 demo users with temporary passwords, every phone waiting, no surveys). Done: 6.1 stack, 6.2 backup/restore, 6.3 APK download + `/app/version`, 6.4 server setup, 6.5 data, 6.8 Phones screen in the app. Not yet: laptop fallback (6.6), release key and first APK (6.7), the worker container (no `backend/app/worker.py` yet). Commands: `deploy/README.md`.

## Server (decided 13 Nov)

- **Bluehost VPS**, replaces the Hostinger KVM 4 of the SRS: 4 vCPU, 16 GB DDR5, 100 GB NVMe, Ubuntu 24.04 LTS, monthly ₹1,504. No India region. Logged in `docs/change_log.md` (13 Nov); the client was told on 13 Nov (data outside India, 100 GB).
- Bluehost names the key "FunctionalServer"; on the laptop it is `~/.ssh/id_ed25519`.
- Checked in the Bluehost panel 13 Nov: no snapshots or backups (switched off when ordering), no panel firewall (ufw on the server is the only one). Phone on mobile data: `/health` ok, no certificate warning.
- So until 12.5 (office computer pulls the dumps) every backup lives only on this server: losing the VPS loses them too. Copy a dump to the laptop by hand after important data changes (`scp deploy@50.6.44.108:/var/backups/jansetu/<file>.dump jansetu-private/backups/`).
- Set up 13 Nov with `deploy/server_setup.sh` and `deploy/make_env.sh` (see `deploy/README.md`): Docker 29.9 + compose v5.7 from Docker's apt repo, ufw (22, 80, 443 tcp, 443 udp), unattended security upgrades, Docker log limit 10 MB x 5, cron + logrotate (not in Bluehost's minimal image). Code in `/srv/jansetu` (copied with `git archive`, no git on the server), server `.env` there (mode 600, passwords generated on the server, never copied off). Server clock UTC.
- Tested 13 Nov: HTTPS with a Let's Encrypt certificate for `myjansetu.com` and `www` (www → 301 to the main name, http → 308), `/health` ok, `/app/version` 404 (nothing published), 5432 closed from outside; backup + restore check on the server (47 tables); after `sudo reboot` all containers, ufw and the SSH lockdown came back by themselves.
- Audit 13 Nov: `backup.sh` run with cron's bare environment (`env -i`, PATH `/usr/bin:/bin`) works; the first real cron run is 21:00 UTC on 13 Nov, check `/var/log/jansetu/backup.log` after it. Unattended upgrades install kernels but never reboot (`Automatic-Reboot` is off): when `/var/run/reboot-required` exists, `sudo systemctl reboot` at a quiet time (done 13 Nov, kernel 6.8.0-149; everything came back by itself), or switch automatic reboots on in 12.7. A reboot from the Bluehost panel did not take effect on 13 Nov; check `uptime` afterwards. `/api/v1/docs` and `/api/v1/openapi.json` are public until 12.7.
- 6.5 done 13 Nov: dev dump `jansetu_20261113T075540Z` (laptop backup xid 215,380) restored with `restore.sh --live`; counts matched (47 tables); counter moved 2,196 → 2,215,385; then `migrate.py` (role passwords); rehearsal data removed (4 surveys, 6 sync records, sessions ended; audit log kept, it is append-only); `create_demo_users.py --reset` (all 4 users new temporary passwords, phones pending). Checked: 31,871 voters (API role: 0 without context, 31,871 in `naik`), the laptop password of demo.admin is refused, the new temporary one logs in with must-change. Server dump `jansetu_20261113T075759Z` copied to the laptop's `jansetu-private/backups/`.
- Server demo passwords: `jansetu-private/demo_users_server.txt` on the laptop (temporary, each user sets a new one at first login). The demo admin's phone is approved with `approve_phone.py` after its first login.
- Checked 13 Nov: IP 50.6.44.108 (`myjansetu.com` and `www` point to it, no AAAA record), Ubuntu 24.04.5, 4 cores, 15 GiB, 96 GB disk.

## SSH (locked down 13 Nov)

- Log in as **`deploy`** with the "FunctionalServer" key: `ssh deploy@50.6.44.108`. `deploy` is in the `sudo` group with passwordless sudo (`/etc/sudoers.d/90-deploy`), because it has no password.
- `/etc/ssh/sshd_config.d/00-jansetu.conf`: `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`, `PubkeyAuthentication yes`, `AllowUsers deploy`. It is loaded first, so it wins over Bluehost's `50-cloud-init.conf` and `51_permit_root_login.conf` (both say yes; sshd keeps the first value). Do not edit Bluehost's files; they may be rewritten.
- Tested 13 Nov: deploy key login and sudo work; root is refused; the server offers only `publickey`.
- Root's `authorized_keys` still holds `access@hal` (most likely Bluehost support) and our key; both are unused while root login is off. If Bluehost support needs SSH, they will have to ask.
- The laptop key has a passphrase and is loaded in the Windows ssh-agent (service on Automatic). Use Windows `ssh.exe` (PowerShell); Git Bash's ssh does not see that agent.
- Locked out? Use the VNC / console in the Bluehost panel (does not go through SSH), log in as root with the root password, and fix `00-jansetu.conf`.
- Adding a second admin later: add their key to `/home/deploy/.ssh/authorized_keys`, or create a user and add it to `AllowUsers`.
- Before applying a new sshd change: `sudo sshd -t`, then `sudo systemctl reload ssh`, and test a new connection while the old one is still open.

## Production stack (`deploy/docker-compose.yml`, project `jansetu`)

| Service | What |
|---|---|
| `db` | `postgres:16-bookworm`, volume `pgdata`, **no host port**. Memory from `PG_SHARED_BUFFERS` / `PG_EFFECTIVE_CACHE_SIZE` (server 4GB / 10GB, laptop 512MB / 2GB) |
| `api` | image `jansetu-api` from `backend/Dockerfile`, uvicorn, `API_WORKERS` processes x `DB_POOL_SIZE` (x2 overflow) connections; port 8000 only inside the network. Gets only the app role password and the JWT secret |
| `caddy` | `caddy:2.10`, ports 80/443 (+443/udp). `/api/*` → api; `/download/<name>.apk` → `deploy/apk/`; anything else 404 until the portal (9.9). `www` redirects to `DOMAIN`. Certificates in volume `caddy_data` (keep it: Let's Encrypt limits new certificates) |
| `ops` | same image, profile `ops`, for one-off scripts; the only container with the superuser and owner passwords |

Commands (repo root; compose reads `deploy/.env`):

```
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml run --rm ops python scripts/migrate.py
docker compose -f deploy/docker-compose.yml run --rm ops python scripts/create_super_admin.py ...
curl -k https://localhost/api/v1/health          # laptop (SITE_ADDRESS=localhost)
docker compose -f deploy/docker-compose.yml down # keeps the volumes; `down -v` deletes the data
```

- Laptop and server use the same compose file; only `deploy/.env` differs (`SITE_ADDRESS`, sizes). Server: `SITE_ADDRESS=myjansetu.com, www.myjansetu.com`.
- The dev database (`docker-compose.dev.yml`, project `jansetu-dev`, port 5442) is separate; both can run at once.
- Image contents are an allow-list (`.dockerignore`): backend code, `db/`, `scripts/`. Nothing from `jansetu-private/` or `.env` can enter it. Python packages pinned by `backend/constraints.txt` (refresh with `pip freeze --exclude-editable` after a dependency change).
- A fresh `db` has no `jansetu_app` role, so `/health` is 503 until `migrate.py` has run.
- Tested 13 Nov on the laptop: health 200 through Caddy, http → https 308, unknown path 404, API errors keep their JSON shape, client IP passed through from Caddy.

## Backups (`scripts/backup.sh`, `scripts/restore.sh`)

- `backup.sh [DIR]`: `pg_dump -Fc` of the live database through the `db` container, checked with `pg_restore --list`, then `jansetu_<UTC>.dump` + `jansetu_<UTC>.counts` (row count per table, `# xid` = transaction counter). Default DIR `/var/backups/jansetu`, mode 700. Deletes dumps 14 days or older (`KEEP_DAYS`), only after the new one is good. Real voter data: never into the repo.
- `restore.sh DUMP [DB]`: restore check into a scratch database (`jansetu_restore_check`), counts compared with the `.counts` file, then dropped (`KEEP=1` keeps it). Exit 2 if counts differ.
- `restore.sh --live DUMP`: replaces the live database; refuses while the api runs. Creates the two roles if missing (a new server; then run `migrate.py` via ops for their passwords) and the database-level grants that `pg_dump` does not carry.
- **New server = new transaction counter.** `sync_xid` and phone watermarks are transaction numbers of the old server; a fresh one starts near 1,000, so phones would stop getting changes. `--live` moves the counter past max(backup `# xid`, every xid8 in the data) + `XID_MARGIN` (2,000,000, for phones that synced after the backup) with `pgbench`. Laptop: 2.2 million in about a minute. Same server: nothing to do. Needed for 6.5 too (dev database → server).
- `COMPOSE_FILE` picks the stack (default production). Laptop test on the dev database: `COMPOSE_FILE=deploy/docker-compose.dev.yml bash scripts/backup.sh jansetu-private/backups`.
- Server cron (6.4), deploy user, server clock UTC: `0 21 * * * /srv/jansetu/scripts/backup.sh >> /var/log/jansetu/backup.log 2>&1` (02:30 India time). The office computer pulls the dumps in 12.5.
- Tested 13 Nov on the laptop with the real roll: dump 2.1 MB in 3 s; restore check 47 tables match; `--live` into the fresh laptop production stack: counts match, counter 1,490 → 2,201,724, `/health` ok, RLS shows 0 voters without context and 31,871 for workspace naik; retention deletes 14+ days and keeps other files.

## APK publishing (6.3)

Published: **0.1.0** (versionCode 1, required) on 13 Nov, `/download/jansetu-0.1.0.apk`, 34 MB, SHA-256 `1566ae7a…22806`. `/app/version` answers it without a token; the download through Caddy matched the hash. Phone test 13 Nov: the Samsung on mobile data downloaded it from `apk_url`, installed it, logged in as demo.admin against the server, was approved with `approve_phone.py` and downloaded the roll.


1. Build the **signed release** APK (`gradlew assembleRelease`; key and settings: `context/android.md`, Release build). Raise `versionCode` first.
2. Copy it into `deploy/apk/` with its version in the name (server: `scp app-release.apk deploy@50.6.44.108:/srv/jansetu/deploy/apk/jansetu-0.2.0.apk`), plus `output-metadata.json` from the same build folder, renamed entries matching.
3. `docker compose -f deploy/docker-compose.yml run --rm ops python scripts/publish_apk.py deploy/apk/jansetu-0.2.0.apk [--version-code N --version-name X] [--required] [--notes-en ...]`
4. Check `https://myjansetu.com/api/v1/app/version` and download `apk_url` on a phone.

- `publish_apk.py` refuses: a file outside `deploy/apk/`, odd file names, non-zip files, unsigned APKs (no v2/v3 signing block), debug builds (from `output-metadata.json`), a `versionCode` not above every published one, a file name already published.
- Never replace a published file: phones check its SHA-256. A new version = a new file.
- `--required` sets the minimum: apps below it must update. The per-workspace `min_app_version_code` setting is separate (used after login, 7.9).
- Caddy serves only `^/[A-Za-z0-9._-]+\.apk$` under `/download/`, as `application/vnd.android.package-archive`, `Cache-Control: no-cache`; no listing; other names 404. `deploy/apk/*` is git-ignored except `.gitkeep`; `caddy` and `ops` mount it read-only.
- Tested 13 Nov on the laptop with the debug APK (40 MB) as a test row: `/app/version` through Caddy without a token, `apk_url` came out `https://`, downloaded file SHA-256 matched; the CLI refused the debug build; test row and files removed.

## Settings in `deploy/.env`

- `SERVER_HOST`, `SERVER_SSH_USER`, `SERVER_SSH_PORT`, `SERVER_SSH_KEY_PATH`, `SERVER_SSH_PUBLIC_KEY`: laptop side only, the API ignores them (`config.py` has `extra="ignore"`).
- The private key is never pasted into `.env` or copied into the repo; `.env` holds its path.
- `SITE_ADDRESS`, `HTTP_PORT`, `HTTPS_PORT`, `PG_*`, `API_WORKERS`, `DB_POOL_SIZE`: production stack, see above.
- `DOMAIN`, `ACME_EMAIL`: for Caddy. Caddy gets the HTTPS certificate from Let's Encrypt itself; there is no SSL key to paste. The domain's A record must point at the server before `compose up`, and ports 80 and 443 must be open.

## Laptop fallback (6.6)

- If the server is down at the demo: `scriptsallback.ps1` on the laptop, phones with the **debug** build type the laptop's address on the Login screen (details: `context/android.md`, Laptop fallback). The release APK from the server cannot change its address; keep the debug APK installed on the demo phones as the spare.
- The production compose stack on the laptop (`SITE_ADDRESS=localhost`) is not used for the fallback: its HTTPS certificate is Caddy's own, which phones do not trust.

## Pitfalls

- `ops` runs with `--rm`: a script that writes a file inside the container (`create_demo_users.py` writes `jansetu-private/demo_users.txt` and never prints passwords) loses it. Mount a private folder: `run --rm -v /var/backups/jansetu/users:/srv/jansetu/jansetu-private ops ...` (folder owned by uid 10001, mode 700), copy the file off with `sudo cat`, then delete the folder.
- `app.set_context` lasts one transaction: a psql check as `jansetu_app` must run `BEGIN; SELECT app.set_context(...); SELECT ...; COMMIT;`, or it counts 0.

- `docker compose exec -T` reads stdin: in a script piped over SSH (`ssh ... bash -s < file`) it swallows the rest of the script. Run such scripts with `< /dev/null` or as a direct command.
- PowerShell 5.1 strips inner quotes from arguments to `ssh`; put multi-line server commands in a file and send it with `cmd /c "ssh ... bash -s < file"`.

- 100 GB disk: keep Docker image pruning and the 14-day dump rotation; OCR (Step 13) does not run on this server.
