# TG Complaint Bot — MVP (локально + Render)

Две точки входа:
- `main.py` — локальный запуск (polling)
- `app_webhook.py` — вебхук для Render

## Локально
```
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Render
1) Залейте эти файлы в GitHub.
2) На render.com → New → Blueprint → укажите репозиторий.
3) Задайте env: BOT_TOKEN, ADMIN_EMAIL, SMTP_HOST, SMTP_PORT=587, SMTP_USER, SMTP_PASS, FROM_EMAIL (PUBLIC_URL оставьте пустым).
4) После первого деплоя получите URL `https://<name>.onrender.com`, добавьте переменную `PUBLIC_URL` с этим адресом и сделайте Redeploy — вебхук выставится сам.
