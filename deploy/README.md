# JANSETU server: setup and everyday commands

The server is a Bluehost VPS (Ubuntu 24.04, 4 vCPU, 16 GB, 100 GB), IP `50.6.44.108`, domain `myjansetu.com`. Background and decisions: `context/deploy.md`.

Commands marked **laptop** run in PowerShell on the developer laptop, from the repo root. Windows `ssh`/`scp` use the key loaded in the ssh-agent. Commands marked **server** run after `ssh deploy@50.6.44.108`.

## 1. First setup (done 13 Nov 2026)

1. **Bluehost panel:** Ubuntu 24.04, the laptop's public key ("FunctionalServer") for root.
2. **DNS:** A records `@` and `www` → the server IP. No AAAA record.
3. **SSH lockdown** (as root, once): user `deploy` with the same key and passwordless sudo, then `/etc/ssh/sshd_config.d/00-jansetu.conf`:
   ```
   PasswordAuthentication no
   KbdInteractiveAuthentication no
   PermitRootLogin no
   PubkeyAuthentication yes
   AllowUsers deploy
   ```
   `sudo sshd -t && sudo systemctl reload ssh`, then test a new login before closing the old one.
4. **Code** (laptop), from a clean commit:
   ```powershell
   ssh deploy@50.6.44.108 "sudo install -d -o deploy -g deploy -m 755 /srv/jansetu"
   git archive --format=tar -o jansetu.tar HEAD
   scp jansetu.tar deploy@50.6.44.108:/tmp/
   ssh deploy@50.6.44.108 "tar -xf /tmp/jansetu.tar -C /srv/jansetu && rm /tmp/jansetu.tar && chmod -R go-w /srv/jansetu"
   Remove-Item jansetu.tar
   ```
   Only committed files go: never `.env`, `jansetu-private/` or dumps.
5. **Packages, Docker, firewall, folders** (server): `bash /srv/jansetu/deploy/server_setup.sh`, then log out and in (docker group).
6. **Settings** (server): `bash /srv/jansetu/deploy/make_env.sh myjansetu.com <e-mail for certificate notices>`. Writes `deploy/.env` with new random passwords, mode 600. It never leaves the server.
7. **Start** (server):
   ```bash
   cd /srv/jansetu
   docker compose -f deploy/docker-compose.yml up -d --build
   docker compose -f deploy/docker-compose.yml run --rm ops python scripts/migrate.py
   ```
   Caddy gets the Let's Encrypt certificate within a minute (ports 80 and 443 must be reachable).
8. **Nightly backup** (server): `crontab -e` and add
   ```
   0 21 * * * /srv/jansetu/scripts/backup.sh >> /var/log/jansetu/backup.log 2>&1
   ```
   21:00 UTC = 02:30 India time. Dumps go to `/var/backups/jansetu` (mode 700), 14 days kept.
9. **Check** from a phone on mobile data: `https://myjansetu.com/api/v1/health` → `{"status":"ok","database":"ok",...}`.

## 2. Update the code (laptop, then server)

Commit first, then repeat step 4 (the archive overwrites changed files; files deleted from the repo stay on the server until removed by hand). Then on the server:

```bash
cd /srv/jansetu
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml run --rm ops python scripts/migrate.py
curl -s https://myjansetu.com/api/v1/health
```

`up -d --build` restarts only containers whose image or settings changed; the database volume is kept.

## 3. Everyday commands (server, in `/srv/jansetu`)

| What | Command |
|---|---|
| State of the containers | `docker compose -f deploy/docker-compose.yml ps` |
| API log (last 100 lines) | `docker compose -f deploy/docker-compose.yml logs --tail 100 api` |
| Caddy log (certificates, requests) | `docker compose -f deploy/docker-compose.yml logs --tail 100 caddy` |
| Database shell (superuser; RLS does not apply) | `docker compose -f deploy/docker-compose.yml exec db psql -U postgres -d jansetu` |
| Restart the API | `docker compose -f deploy/docker-compose.yml restart api` |
| Backup now | `scripts/backup.sh` |
| Restore check of a dump | `scripts/restore.sh /var/backups/jansetu/<file>.dump` |
| Backup log | `tail /var/log/jansetu/backup.log` |
| Create a super admin | `docker compose -f deploy/docker-compose.yml run --rm ops python scripts/create_super_admin.py --username ... --name "..."` |
| New temporary password for a super admin (ends their sessions, phones back to pending) | `docker compose -f deploy/docker-compose.yml run --rm ops python scripts/create_super_admin.py --username ... --reset` |
| Publish an APK | see `context/deploy.md`, "APK publishing" |
| Disk space | `df -h /` and `docker system df` |
| Remove old images after updates | `docker image prune -f` |

## 4. When something is wrong

- **Locked out of SSH:** Bluehost panel → VPS → console (does not use SSH). Log in as root with the root password and fix `/etc/ssh/sshd_config.d/00-jansetu.conf`.
- **Restore the live database** (same server or a new one): `docker compose -f deploy/docker-compose.yml stop api`, then `scripts/restore.sh --live <dump>`, then `run --rm ops python scripts/migrate.py`, then `start api`. On a new server `--live` also moves the transaction counter so phones keep syncing (see `context/deploy.md`, Backups).
- **Certificate errors:** `logs caddy`; check that DNS still points at the server and that ports 80/443 are open (`sudo ufw status`).
- **After a reboot** everything starts by itself (`restart: unless-stopped`; tested 13 Nov).
