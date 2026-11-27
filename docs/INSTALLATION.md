# Installation Guide (Ubuntu 24.04 LTS)

## 1. System Prerequisites

Update Ubuntu 24.04 and install Docker Engine, Docker Compose v2, Certbot, and UFW:

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg ufw certbot
```

Install Docker using the official Docker repository, then add your deploy user to the `docker` group:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
docker --version
docker compose version
```

## 2. Firewall Configuration

Allow only SSH, HTTP (for ACME challenges/HTTPS redirect), and HTTPS:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status
```

MySQL (`3306`) and Redis (`6379`) remain on the internal Docker `data` network and are never published to the host.

## 3. Application Setup

Place the repository at `/opt/jobhunter-ai` and create the production environment file:

```bash
cd /opt/jobhunter-ai
cp .env.production.example .env
chmod 600 .env
```

Generate strong random secrets (`SECRET_KEY`, `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`):

```bash
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('MYSQL_PASSWORD=' + secrets.token_urlsafe(24))"
python3 -c "import secrets; print('MYSQL_ROOT_PASSWORD=' + secrets.token_urlsafe(24))"
```

Populate `.env` with those generated secrets plus your Telegram Bot token, SMTP credentials, and AI provider settings. Never commit `.env` or `certs/` to version control.
