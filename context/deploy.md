# Deploy: server, Docker Compose, Caddy, backups, APK

Current state (13 Nov): step 6 started on branch `step6-server`. Only the dev database container exists (`deploy/docker-compose.dev.yml`). Production compose, Caddyfile, Dockerfile, backup scripts and `deploy/README.md` are not written yet (plan 6.1–6.4).

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

## Settings in `deploy/.env`

- `SERVER_HOST`, `SERVER_SSH_USER`, `SERVER_SSH_PORT`, `SERVER_SSH_KEY_PATH`, `SERVER_SSH_PUBLIC_KEY`: laptop side only, the API ignores them (`config.py` has `extra="ignore"`).
- The private key is never pasted into `.env` or copied into the repo; `.env` holds its path.
- `DOMAIN`, `ACME_EMAIL`: for Caddy. Caddy gets the HTTPS certificate from Let's Encrypt itself; there is no SSL key to paste. The domain's A record must point at the server before `compose up`, and ports 80 and 443 must be open.

## Pitfalls

- 100 GB disk: keep Docker image pruning and the 14-day dump rotation; OCR (Step 13) does not run on this server.
