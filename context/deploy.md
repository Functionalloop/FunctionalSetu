# Deploy: server, Docker Compose, Caddy, backups, APK

Current state (13 Nov): step 6 started on branch `step6-server`. Only the dev database container exists (`deploy/docker-compose.dev.yml`). Production compose, Caddyfile, Dockerfile, backup scripts and `deploy/README.md` are not written yet (plan 6.1–6.4).

## Server (decided 13 Nov)

- **Bluehost VPS**, replaces the Hostinger KVM 4 of the SRS: 4 vCPU, 16 GB DDR5, 100 GB NVMe, Ubuntu 24.04 LTS, monthly ₹1,504. No India region. Logged in `docs/change_log.md` (13 Nov); the client still has to agree to data outside India and to 100 GB.
- SSH key only, no password login. Bluehost names the key "FunctionalServer"; on the laptop it is `~/.ssh/id_ed25519`.
- Snapshots: check whether the Bluehost plan has them (6.4).
- Checked 13 Nov: IP 50.6.44.108 (`myjansetu.com` and `www` point to it, no AAAA record), Ubuntu 24.04.5, 4 cores, 15 GiB, 96 GB disk. Key login as root works.
- The laptop key has a passphrase: it is loaded in the Windows ssh-agent (service set to Automatic). Use Windows `ssh.exe` (PowerShell); Git Bash's ssh does not see that agent.
- Still to do in 6.4: password login and root login are on (sshd); `authorized_keys` for root holds our key three times plus `access@hal` (most likely Bluehost's support key; ask before removing).

## Settings in `deploy/.env`

- `SERVER_HOST`, `SERVER_SSH_USER`, `SERVER_SSH_PORT`, `SERVER_SSH_KEY_PATH`, `SERVER_SSH_PUBLIC_KEY`: laptop side only, the API ignores them (`config.py` has `extra="ignore"`).
- The private key is never pasted into `.env` or copied into the repo; `.env` holds its path.
- `DOMAIN`, `ACME_EMAIL`: for Caddy. Caddy gets the HTTPS certificate from Let's Encrypt itself; there is no SSL key to paste. The domain's A record must point at the server before `compose up`, and ports 80 and 443 must be open.

## Pitfalls

- 100 GB disk: keep Docker image pruning and the 14-day dump rotation; OCR (Step 13) does not run on this server.
