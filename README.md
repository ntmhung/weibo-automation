# Weibo snscrape (Docker) → n8n → Telegram Topics → Google Sheets

## 1) Setup
1. Copy `.env.example` to `.env`
2. Set a strong token:
   - `openssl rand -hex 32`
3. Edit `accounts.json` (add your Weibo numeric user IDs)

## 2) Run
```bash
docker compose up -d --build