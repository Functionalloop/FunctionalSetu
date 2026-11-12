# Deploy: server, Docker Compose, Caddy, backups, APK

Current state (13 Nov): branch `step6-server`. 6.1 done: production stack (`deploy/docker-compose.yml`, `deploy/Caddyfile`, `backend/Dockerfile`) runs on the laptop. Not yet: backups (6.2), APK and `/app/version` (6.3), the stack on the server and `deploy/README.md` (6.4), the worker container (no `backend/app/worker.py` yet).

## Server (decided 13 Nov)

- **Bluehost VPS**, replaces the Hostinger KVM 4 of the SRS: 4 vCPU, 16 GB DDR5, 100 GB NVMe, Ubuntu 24.04 LTS, monthly ₹1,504. No India region. Logged in `docs/change_log.md` (13 Nov); the client still has to agree to data outside India and to 100 GB.
- Bluehost names the key "FunctionalServer"; on the laptop it is `~/.ssh/id_ed25519`.
- Snapshots: check whether the Bluehost plan has them (6.4).
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
- Still to do in 6.4: firewall (ufw: 22, 80, 443), Docker, compose up.

## Production stack (`deploy/docker-compose.yml`, project `jansetu`)

| Service | What |
|---|---|
| `db` | `postgres:16-bookworm`, volume `pgdata`, **no host port**. Memory from `PG_SHARED_BUFFERS` / `PG_EFFECTIVE_CACHE_SIZE` (server 4GB / 10GB, laptop 512MB / 2GB) |
| `api` | image `jansetu-api` from `backend/Dockerfile`, uvicorn, `API_WORKERS` processes x `DB_POOL_SIZE` (x2 overflow) connections; port 8000 only inside the network. Gets only the app role password and the JWT secret |
| `caddy` | `caddy:2.10`, ports 80/443 (+443/udp). `/api/*` → api; anything else 404 until the APK (6.3) and portal (9.9). `www` redirects to `DOMAIN`. Certificates in volume `caddy_data` (keep it: Let's Encrypt limits new certificates) |
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

## Settings in `deploy/.env`

- `SERVER_HOST`, `SERVER_SSH_USER`, `SERVER_SSH_PORT`, `SERVER_SSH_KEY_PATH`, `SERVER_SSH_PUBLIC_KEY`: laptop side only, the API ignores them (`config.py` has `extra="ignore"`).
- The private key is never pasted into `.env` or copied into the repo; `.env` holds its path.
- `SITE_ADDRESS`, `HTTP_PORT`, `HTTPS_PORT`, `PG_*`, `API_WORKERS`, `DB_POOL_SIZE`: production stack, see above.
- `DOMAIN`, `ACME_EMAIL`: for Caddy. Caddy gets the HTTPS certificate from Let's Encrypt itself; there is no SSL key to paste. The domain's A record must point at the server before `compose up`, and ports 80 and 443 must be open.

## Pitfalls

- 100 GB disk: keep Docker image pruning and the 14-day dump rotation; OCR (Step 13) does not run on this server.
