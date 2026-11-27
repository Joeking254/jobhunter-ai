# Troubleshooting Guide

## 1. `/api/health/ready` Returns `503`
- Check container status and logs:
  `docker compose --env-file .env -f compose.yml -f compose.prod.yml ps`
  `docker compose --env-file .env -f compose.yml -f compose.prod.yml logs --tail=100 backend mysql redis`
- Verify `MYSQL_PASSWORD` in `.env` matches the initialized MySQL volume password.

## 2. `502 Bad Gateway` from Nginx
- Ensure `backend` and `frontend` passed health checks.
- Verify Nginx config syntax:
  `docker compose --env-file .env -f compose.yml -f compose.prod.yml exec nginx nginx -t`

## 3. TLS / SSL Certificate Renewal Errors
- Ensure port `80` is open in UFW (`sudo ufw allow 80/tcp`) and DNS for `jobs.jkdesignke.com` points to the server.
- Confirm `./certbot/www` is mounted to `/var/www/certbot` in `compose.prod.yml`.
- Re-run `/opt/jobhunter-ai/scripts/renew_ssl.sh /opt/jobhunter-ai`.

## 4. Background Tasks Not Running or Stuck
- Inspect worker health and queue depths via `GET /api/monitoring/summary` or `GET /api/bot/status`.
- Check if the bot or auto-apply was paused in the dashboard (`BotConfig.bot_paused` / `auto_apply_paused`).
- View worker/scheduler logs:
  `docker compose --env-file .env -f compose.yml -f compose.prod.yml logs -f worker scheduler`

## 5. Applications Paused in `confirmation_pending`
- Check `last_error` in **Application History** or **Pending Approvals**. CAPTCHA, MFA, login walls, application fees, and unconfirmed legal declarations intentionally pause automation and notify the owner.

## 6. Telegram or SMTP Notification Failures
- Inspect delivery errors on **Notification Settings -> Delivery Logs** (`GET /api/notifications/deliveries`), verify `TELEGRAM_BOT_TOKEN` / `SMTP_*` variables in `.env`, and trigger **Retry Failed** (`POST /api/notifications/retry`).
