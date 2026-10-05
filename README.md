# Navnidh Traders – Flask Chair Shop

## Run locally (Chrome)
1. Install Python 3.10+.
2. `cd navnidh_traders && python -m venv venv`, then activate it (`venv\Scripts\activate` on Windows, `source venv/bin/activate` on Mac/Linux).
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and edit it (set WHATSAPP_NUMBER like 919876543210, admin email/password).
5. `python app.py` then open http://127.0.0.1:5000 in Chrome.

Tables, demo products and the admin account are created automatically on first run (SQLite by default).

## Use MySQL
Create the DB: `CREATE DATABASE navnidh_traders CHARACTER SET utf8mb4;`
Then in `.env` set `DATABASE_URL=mysql+pymysql://root:PASSWORD@localhost/navnidh_traders?charset=utf8mb4` and run `python app.py` (or `flask --app app seed`).

## Admin
Log in at /login with ADMIN_EMAIL / ADMIN_PASSWORD from `.env`, then use the Admin button. Change the default password before going live.

## Placeholders to fill
Address, phone, email, hours, Google Maps and return policy (search for `[` in templates).
