# Carewell Clinic — Production Deployment Preparation

This package is a prepared copy of the previously tested Flask application plus the website. **It has NOT been deployed or tested against a live Neon PostgreSQL database.** Test it in a separate project folder first. Do not overwrite your working project without backing it up.

## 1. Run locally on Windows CMD

1. Extract the ZIP into a **new** folder named `clinic_booking_production_test`.
2. In CMD, enter that folder and create/activate a virtual environment:
   ```cmd
   py -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env`:
   ```cmd
   copy .env.example .env
   ```
4. Generate **two different** secrets:
   ```cmd
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   Run twice; set `API_KEY` and `WEB_SESSION_SECRET` in `.env`. Keep `APP_ENV=development`, `COOKIE_SECURE=0`; do **not** set `DATABASE_URL` yet.
5. Test:
   ```cmd
   python -m py_compile app.py models.py database.py web_ui.py
   python app.py
   ```
   Visit `http://127.0.0.1:5000/`. Populate future slots via authenticated `POST /reset`. This creates a **separate** SQLite instance database in the extracted folder, so your current bookings remain safe.

## 2. Prepare Neon

1. Create a Neon project and PostgreSQL database.
2. From Neon **Connect**, copy a database connection string. Preserve `sslmode=require` or stricter.
3. Use a pooled URL for the web application and a direct URL for future migrations.
4. Never commit credentials into Git.

## 3. Verify against PostgreSQL **before** public deployment

1. Set `DATABASE_URL` in a separate private `.env` file (or OS environment). A Neon `postgresql://` URL is automatically converted to SQLAlchemy's `postgresql+psycopg://` dialect.
2. Start locally and check that `db.create_all` and the partial unique booking index succeed.
3. Seed only disposable test slots using `POST /reset`, then re-run your independent regression suite. **WARNING:** POST /reset permanently wipes bookings, idempotency records, and rate limit attempts on whichever DATABASE_URL is currently configured.
4. Verify six simultaneous requests from one email produce five processed attempts and a sixth 429, plus same-key idempotency replay and concurrent booking/cancel tests.

## 4. Deploy API + website together on Render

1. Push this folder to your GitHub repo; `.env`, SQLite files, and venv are excluded by `.gitignore`.
2. In Render, create a Web Service from that repository, or use `render.yaml` as a Blueprint.
3. Set secret environment variables `DATABASE_URL`, `API_KEY`, `WEB_SESSION_SECRET`. Keep `APP_ENV=production`, `COOKIE_SECURE=1`.
4. Build: `pip install -r requirements.txt`.
5. Start: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 60 app:app`.
6. Confirm public `https://<your-service>.onrender.com/` loads the clinic website; verify `/slots` with `X-API-Key` and create/retrieve a booking. The API and website may share the same hostname, but submit their corresponding URLs separately.
7. After final verification, stop sending `/reset` against production data. Before submitting, freeze changes and disable Render Auto-Deploy to avoid unexpected changes.

## Notes
- SQLAlchemy creates tables on startup; for a real versioned production schema, use Alembic/Flask-Migrate in later iterations.
- The rate limiter uses `BEGIN IMMEDIATE` on SQLite and PostgreSQL transaction-scoped `pg_advisory_xact_lock(hashtextextended(email,0))` on PostgreSQL. The lock only coordinates application instances using this algorithm.
- A Render free web service may spin down when inactive. Confirm the hosting plan's current behavior meets the assessment's uptime requirement before submitting.
- The current `POST /reset` is test-oriented and destructive; preserve it for the grader but restrict the API key carefully.
- If Koya expects the API key in the form, submit the secret you configured in Render, not the web session secret.
