# Carewell Clinic — Appointment Booking API & Web App

A full-stack clinic appointment booking application built with **Python, Flask, SQLAlchemy, PostgreSQL, HTML, CSS and JavaScript**. Patients can browse available appointments, choose a provider, book a slot and view a confirmation. A JSON API supports authenticated booking management, safe concurrent bookings, idempotent retries, cursor pagination and per-email rate limiting.

Developed for the **Koya Academy Cohort 4 — Booking API assessment** (Levels 1–5).

## Live application

| Resource                           | Link                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------ |
| Patient booking website            | `https://clinic-production-ready.onrender.com`                           |
| API base URL                       | `https://clinic-production-ready.onrender.com`                           |
| Technical assessment specification | [Koya Academy API specification](https://koyaacademy.com/assessment-api) |

## Features

- **Appointments:** List all slots in chronological order, filter by provider, and show booking availability.
- **Booking:** Create confirmed appointments and retrieve a booking by its ID.
- **Validation:** Reject incomplete or invalid booking data, unknown slots and appointments that have already started; normalize patient names and email addresses.
- **Authentication:** Require `X-API-Key` for assessment API routes.
- **Concurrency safety:** Enforce at most one _confirmed_ booking per slot using a database partial unique index.
- **Cancellation:** Mark a booking as `cancelled`, preserve its history and make its slot available again.
- **Idempotency:** Use an optional `Idempotency-Key` header to replay stored responses on matching retries and reject key reuse with a different body.
- **Booking history:** Filter by email (case-insensitively) with cursor-based pagination, oldest first.
- **Rate limiting:** Allow up to five booking attempts per email within a rolling 60-second window; return `429` and a `Retry-After` header when exceeded.
- **Patient website:** Responsive appointment cards, provider filtering, booking form and confirmation dialog. The server-side integration keeps the API key out of browser JavaScript.

## Technology stack

| Layer                      | Technology                                        |
| -------------------------- | ------------------------------------------------- |
| API/backend                | Python, Flask                                     |
| Database access            | Flask-SQLAlchemy / SQLAlchemy                     |
| Local development database | SQLite                                            |
| Hosted database            | Neon PostgreSQL (Psycopg)                         |
| Frontend                   | HTML, CSS, vanilla JavaScript                     |
| Production web server      | Gunicorn                                          |
| Hosting                    | Render                                            |
| Testing                    | Postman and Python regression/concurrency scripts |

## API reference

All assessment API endpoints require the request header `X-API-Key: <your-key>` and use JSON for request and response bodies (where applicable).

| Method   | Endpoint              | Description                                                                          |
| -------- | --------------------- | ------------------------------------------------------------------------------------ |
| `POST`   | `/reset`              | Replace all slots and clear existing bookings (destructive assessment/test endpoint) |
| `GET`    | `/slots`              | List slots; optionally filter with `?provider=Dr%20Ade`                              |
| `POST`   | `/bookings`           | Create a booking with `slot_id`, `name` and `email`                                  |
| `GET`    | `/bookings/{id}`      | Get a booking by its ID                                                              |
| `DELETE` | `/bookings/{id}`      | Cancel a confirmed booking                                                           |
| `GET`    | `/bookings?email=...` | List a patient's bookings with optional `limit` (1–50; default 10) and `cursor`      |

### Create a booking

```http
POST /bookings
X-API-Key: YOUR_API_KEY
Idempotency-Key: optional-unique-key
Content-Type: application/json
```

```json
{
  "slot_id": "s1",
  "name": "Ada Obi",
  "email": "ada@example.com"
}
```

Successful responses return `201 Created` and a booking object:

```json
{
  "id": "generated-booking-uuid",
  "slot_id": "s1",
  "name": "Ada Obi",
  "email": "ada@example.com",
  "status": "confirmed",
  "created_at": "2026-11-13T10:00:00.000Z"
}
```

### List appointments

```http
GET /slots?provider=Dr%20Ade
X-API-Key: YOUR_API_KEY
```

Response:

```json
{
  "slots": [
    {
      "id": "s1",
      "provider": "Dr Ade",
      "start": "2026-12-10T09:00:00Z",
      "end": "2026-12-10T09:30:00Z",
      "available": true
    }
  ]
}
```

### Paginate booking history

```http
GET /bookings?email=ada%40example.com&limit=2
X-API-Key: YOUR_API_KEY
```

Pass the `next_cursor` returned by this request as the `cursor` query parameter to retrieve the following page. The last page returns `"next_cursor": null`.

### Important status codes

| Status | Meaning                                                |
| ------ | ------------------------------------------------------ |
| `200`  | Successful read, reset or cancellation                 |
| `201`  | Booking created                                        |
| `400`  | Invalid input or appointment already started           |
| `401`  | Missing or invalid API key                             |
| `404`  | Requested booking or slot not found                    |
| `409`  | Slot already booked or booking already cancelled       |
| `422`  | Idempotency key reused with a different request body   |
| `429`  | Rate limit exceeded; see `Retry-After` response header |

> Error responses use a JSON `error` field. The exact message varies by failure.

## Project structure

```text
.
├── app.py               # Flask API routes, validation and booking logic
├── models.py            # Slot, Booking, IdempotencyRecord, RateLimitAttempt
├── database.py          # SQLAlchemy initialization
├── web_ui.py            # Patient-facing website routes and secure API bridge
├── templates/
│   └── index.html       # Website markup
├── static/
│   ├── style.css        # Website styles
│   └── script.js        # Browser interactions
├── requirements.txt     # Python dependencies
├── render.yaml          # Render deployment blueprint
├── .env.example         # Environment-variable example (no real secrets)
└── README_DEPLOY.md     # Additional deployment notes
```

## Run locally (Windows CMD)

**Requirements:** Python and pip installed.

1. Clone the repository and enter the project directory:

   ```cmd
   git clone https://github.com/Habinger/clinic_production_ready
   cd YOUR_REPO
   ```

2. Create and activate a virtual environment:

   ```cmd
   py -m venv venv
   venv\Scripts\activate
   ```

3. Install dependencies:

   ```cmd
   pip install -r requirements.txt
   ```

4. Create a private environment file:

   ```cmd
   copy .env.example .env
   ```

   Generate two **different** random secrets:

   ```cmd
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

   Run the generator twice, and use its outputs as the values of `API_KEY` and `WEB_SESSION_SECRET` in `.env`.

   For local SQLite testing, leave `DATABASE_URL` unset and set `APP_ENV=development`, `COOKIE_SECURE=0`.

5. Start Flask:

   ```cmd
   python app.py
   ```

   Open **http://127.0.0.1:5000/** in a browser. The local SQLite database is initialized on startup. Populate **future** appointment slots using the authenticated `POST /reset` endpoint if the database is empty.

> **Windows note:** Gunicorn does not run natively on Windows. Use `python app.py` for local development; Render runs Gunicorn on Linux.

## Environment variables

| Variable             | Description                                                           |
| -------------------- | --------------------------------------------------------------------- |
| `API_KEY`            | Secret required for the assessment API via `X-API-Key`                |
| `WEB_SESSION_SECRET` | Secret used by the web interface/session integration                  |
| `DATABASE_URL`       | PostgreSQL URL from Neon for hosted deployment; omit for local SQLite |
| `APP_ENV`            | `development` locally; `production` on Render                         |
| `COOKIE_SECURE`      | `0` for local HTTP; `1` for production HTTPS                          |

Do not commit `.env` or paste production secrets into issues, pull requests or screenshots.

## Deploy on Render with Neon

1. Create a Neon PostgreSQL database and obtain its connection URL, including the appropriate TLS options.
2. Push the project to GitHub (excluding `.env`, `venv/` and local database files).
3. Create a Render **Web Service** connected to the repository, or use the included `render.yaml`.
4. Configure the required secret environment variables in Render: `API_KEY`, `WEB_SESSION_SECRET`, `DATABASE_URL`; set `APP_ENV=production` and `COOKIE_SECURE=1`.
5. Use the build and start commands:

   ```bash
   pip install -r requirements.txt
   ```

   ```bash
   gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 60 app:app
   ```

6. Test the HTTPS website and authenticated API endpoints against Neon. **Do not run destructive reset tests against real data.**
7. Once submitted for assessment, keep the service accessible and avoid changes until Koya contacts you. Consider the hosting plan's idle/sleep behavior and disable automatic deployments when you freeze the submission.

See [`README_DEPLOY.md`](README_DEPLOY.md) for more detailed deployment guidance.

## Testing

The project has been tested locally using Postman and Python scripts, including concurrency and regression checks. The reported local regression run passed **8/8 scenarios** covering:

1. Authentication and slots
2. Validation and reset
3. Booking and cancellation
4. Idempotency (success, failure and replay)
5. Cursor pagination
6. Rate limiting and `Retry-After`
7. Concurrent bookings
8. Concurrent idempotent retries

These are **local test results**, not a claim that the same suite has run successfully against the deployed Neon/Render environment. Re-run integration checks against the hosted service before submitting.

## Security and assessment notes

- The patient-facing UI uses server-side Flask routes (`/web/slots`, `/web/bookings`) so the secret API key does not need to be embedded in client-side JavaScript.
- The authenticated `POST /reset` endpoint is deliberately destructive for assessment setup. Keep its key private and never run it against valuable production bookings.
- The one-confirmed-booking-per-slot invariant is backed by a database partial unique index, not only a Python pre-check.
- Idempotency results and rate-limit attempts are persisted in the database.
- The assessment requires the deployed **API base URL**, **API key**, **website URL**, **GitHub repository**, and a **Loom video of five minutes or less** showing the website and code walkthrough.

## Assessment

Built as a practical implementation of the **Koya Academy Cohort 4 Booking API** requirements. The application demonstrates RESTful API design, validation, authentication, database consistency, concurrency handling, idempotent operations, pagination, rate limiting and deployment of a patient-facing web experience.
