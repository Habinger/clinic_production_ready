import hashlib
import math
import time
import json
from datetime import datetime, timezone
import os
import re
import uuid
from functools import wraps
import secrets
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from flask import Flask, jsonify, request
from dotenv import load_dotenv
import base64
from sqlalchemy import and_, or_, func
from database import db
from models import Slot, Booking, IdempotencyRecord, RateLimitAttempt
import binascii
load_dotenv()

app = Flask(__name__)

app.json.sort_keys = False


# ------------------------------------------------
# LEVEL 2 - API KEY AUTHENTICATION
# ------------------------------------------------

API_KEY = os.getenv("API_KEY")

if not API_KEY:
    raise RuntimeError(
        "API_KEY is missing. Set it in your .env file."
    )


def require_api_key(function):
    @wraps(function)
    def decorated_function(*args, **kwargs):

        # Get the API key supplied by the client
        provided_key = request.headers.get("X-API-Key")

        # Reject requests with missing or incorrect keys
        if (
            provided_key is None
            or not secrets.compare_digest(
                provided_key,
                API_KEY
            )
        ):
            return jsonify({
                "error": "Unauthorized"
            }), 401

        # Allow the request if authentication succeeds
        return function(*args, **kwargs)

    return decorated_function


# Database configuration
database_url = os.getenv("DATABASE_URL")
if os.getenv("APP_ENV") == "production" and not database_url:
    raise RuntimeError("DATABASE_URL is required in production")
if not database_url:
    database_url = "sqlite:///clinic.db"
# Neon publishes postgresql:// URLs. Select psycopg v3 explicitly.
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://"):]
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
}

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def normalize_time(value):
    """Convert an ISO timestamp to UTC."""

    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            raise ValueError("Timezone is required")

        parsed = parsed.astimezone(timezone.utc)

        return parsed.isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")

    except (ValueError, OverflowError):
        raise ValueError("Invalid timestamp")

    
# ------------------------------------------------
# LEVEL 4 - CURSOR PAGINATION HELPERS
# ------------------------------------------------

def encode_cursor(booking):
    """Create a cursor from the last booking."""

    cursor_data = {
        "created_at": booking.created_at,
        "id": booking.id
    }

    cursor_json = json.dumps(
        cursor_data,
        separators=(",", ":")
    )

    return base64.urlsafe_b64encode(
        cursor_json.encode("utf-8")
    ).decode("utf-8").rstrip("=")


def decode_cursor(cursor):
    """Read and validate a pagination cursor."""

    try:
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("Invalid cursor")

        # Restore missing Base64 padding
        padded = cursor + "=" * (-len(cursor) % 4)

        decoded = base64.urlsafe_b64decode(
            padded.encode("ascii")
        )

        cursor_data = json.loads(
            decoded.decode("utf-8")
        )

        if not isinstance(cursor_data, dict):
            raise ValueError("Invalid cursor")

        created_at = cursor_data["created_at"]
        booking_id = cursor_data["id"]

        if (
            not isinstance(created_at, str)
            or not isinstance(booking_id, str)
            or not created_at
            or not booking_id
        ):
            raise ValueError("Invalid cursor")

        return created_at, booking_id

    except (ValueError, KeyError, TypeError,
        UnicodeError, binascii.Error):
        raise ValueError("Invalid cursor")




# POST /reset - Replace all appointment slots


@app.route("/reset", methods=["POST"])
@require_api_key
def reset_slots():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid JSON body"
        }), 400

    slots_data = data.get("slots")

    if not isinstance(slots_data, list):
        return jsonify({
            "error": "slots must be an array"
        }), 400

    new_slots = []
    seen_ids = set()

    try:
        for item in slots_data:

            if not isinstance(item, dict):
                raise ValueError("Invalid slot")

            slot_id = item.get("id")
            provider = item.get("provider")

            if (
                not isinstance(slot_id, str)
                or not slot_id
                or len(slot_id) > 50
            ):
                raise ValueError("Invalid slot ID")

            if slot_id in seen_ids:
                raise ValueError("Duplicate slot ID")

            if (
                not isinstance(provider, str)
                or not provider
                or len(provider) > 100
            ):
                raise ValueError("Invalid provider")

            start = normalize_time(item.get("start"))
            end = normalize_time(item.get("end"))

            if start >= end:
                raise ValueError(
                    "Slot end must be after start"
                )

            seen_ids.add(slot_id)

            new_slots.append(
                Slot(
                    id=slot_id,
                    provider=provider,
                    start=start,
                    end=end
                )
            )

    except ValueError as error:
        return jsonify({
            "error": str(error)
        }), 400

    try:
        # clear the rate limit counter
        db.session.query(RateLimitAttempt).delete()
        # IdempotencyRecord must be removes first
        db.session.query(IdempotencyRecord).delete()
        # Bookings must be removed next
        db.session.query(Booking).delete()
        # Replace the existing slots
        db.session.query(Slot).delete()
        db.session.add_all(new_slots)

        db.session.commit()

    except Exception:
        db.session.rollback()

        return jsonify({
            "error": "Unable to reset slots"
        }), 500

    return jsonify({
        "message": "Slots reset successfully"
    }), 200



# GET /slots - List appointment slots


@app.route("/slots", methods=["GET"])
@require_api_key
def get_slots():

    provider = request.args.get("provider")

    query = db.session.query(Slot)

    if provider is not None:
        query = query.filter(
            Slot.provider == provider
        )

    slots = query.order_by(
        Slot.start.asc(),
        Slot.id.asc()
    ).all()

    return jsonify({
        "slots": [
            slot.to_dict()
            for slot in slots
        ]
    }), 200


def get_request_hash(data):
    """Create a consistent fingerprint of a JSON body."""

    canonical_json = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False
    )

    return hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()


def get_saved_response(record):
    """Return a previously saved API response."""

    return jsonify(
        json.loads(record.response_body)
    ), record.status_code


# ------------------------------------------------
# Process a booking without committing
# ------------------------------------------------

def process_booking(data):

    if not isinstance(data, dict):
        return {"error": "Invalid JSON body"}, 400

    slot_id = data.get("slot_id")
    name = data.get("name")
    email = data.get("email")

    # Validate slot ID
    if (
        not isinstance(slot_id, str)
        or not slot_id
        or len(slot_id) > 50
    ):
        return {"error": "Invalid slot_id"}, 400

    # Validate and normalize name
    if not isinstance(name, str):
        return {"error": "Invalid name"}, 400

    name = name.strip()

    if not name or len(name) > 100:
        return {"error": "Invalid name"}, 400

    # Validate and normalize email
    if not isinstance(email, str):
        return {"error": "Invalid email"}, 400

    email = email.strip().lower()

    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    if (
        len(email) > 254
        or not re.fullmatch(email_pattern, email)
    ):
        return {"error": "Invalid email"}, 400

    # Check that the slot exists
    slot = db.session.get(Slot, slot_id)

    if slot is None:
        return {"error": "Slot not found"}, 404

    # Reject appointments that have started
    slot_start = datetime.fromisoformat(
        slot.start.replace("Z", "+00:00")
    )

    if slot_start <= datetime.now(timezone.utc):
        return {"error": "Slot has already started"}, 400

    # Check for an existing confirmed booking
    existing = db.session.query(Booking.id).filter_by(
        slot_id=slot_id,
        status="confirmed"
    ).first()

    if existing is not None:
        return {"error": "Slot already booked"}, 409

    # Create the booking
    booking = Booking(
        id=str(uuid.uuid4()),
        slot_id=slot_id,
        name=name,
        email=email,
        status="confirmed"
    )

    db.session.add(booking)

    # Write pending changes, but don't commit yet.
    # This also populates created_at.
    db.session.flush()

    return booking.to_dict(), 201


# ------------------------------------------------
# LEVEL 5 - RATE LIMITING
# ------------------------------------------------

RATE_LIMIT = 5
RATE_WINDOW_MS = 60_000


def check_booking_rate_limit(email):
    """Atomically record a booking attempt in a rolling 60-second window.

    SQLite uses BEGIN IMMEDIATE; PostgreSQL uses a per-email transaction
    advisory lock. Both guard the COUNT + INSERT under concurrency.
    """
    email = email.strip().lower()
    with db.engine.connect() as connection:
        dialect = connection.dialect.name
        if dialect == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        elif dialect == "postgresql":
            # PostgreSQL's transaction-scoped lock is automatically released
            # when the transaction commits or rolls back. A 64-bit hash collision
            # only over-serializes two emails; it cannot bypass limits.
            connection.execute(text(
                "SELECT pg_advisory_xact_lock(hashtextextended(:email, 0))"
            ), {"email": email})
        else:
            raise RuntimeError(f"Unsupported rate-limiter database: {dialect}")

        try:
            now_ms = time.time_ns() // 1_000_000
            cutoff = now_ms - RATE_WINDOW_MS
            connection.execute(text("""
                DELETE FROM rate_limit_attempts
                WHERE email = :email AND attempted_at_ms <= :cutoff
            """), {"email": email, "cutoff": cutoff})
            result = connection.execute(text("""
                SELECT COUNT(*) AS attempt_count,
                       MIN(attempted_at_ms) AS oldest
                FROM rate_limit_attempts WHERE email = :email
            """), {"email": email}).one()
            if result.attempt_count >= RATE_LIMIT:
                remaining_ms = result.oldest + RATE_WINDOW_MS - now_ms
                retry_after = max(1, math.ceil(remaining_ms / 1000))
                connection.commit()
                return False, retry_after

            connection.execute(text("""
                INSERT INTO rate_limit_attempts (email, attempted_at_ms)
                VALUES (:email, :attempted_at_ms)
            """), {"email": email, "attempted_at_ms": now_ms})
            connection.commit()
            return True, 0
        except Exception:
            connection.rollback()
            raise


# POST /bookings - Book an appointment


# ------------------------------------------------
# LEVEL 4 - IDEMPOTENT BOOKING CREATION
# ------------------------------------------------

@app.route("/bookings", methods=["POST"])
@require_api_key
def create_booking():

    data = request.get_json(silent=True)

    # Previously completed idempotent requests must replay the original
    # response even if later attempts have exhausted this email's rate limit.
    replay_key = request.headers.get("Idempotency-Key")
    if replay_key is not None:
        if not replay_key or len(replay_key) > 255:
            return jsonify({"error": "Invalid Idempotency-Key"}), 400
        replay_hash = (get_request_hash(data) if data is not None else
                       hashlib.sha256(request.get_data()).hexdigest())
        prior = db.session.get(IdempotencyRecord, replay_key)
        if prior is not None:
            if prior.request_hash != replay_hash:
                return jsonify({"error": "Idempotency key reused with a different body"}), 422
            return get_saved_response(prior)
        db.session.rollback()

    # -----------------------------------------
    # LEVEL 5 - ENFORCE RATE LIMIT
    # -----------------------------------------

    email_for_limit = None

    if isinstance(data, dict):
        submitted_email = data.get("email")

        if isinstance(submitted_email, str):
            normalized_email = submitted_email.strip().lower()

            if normalized_email:
                email_for_limit = normalized_email

    if email_for_limit is not None:

        try:
            allowed, retry_after = check_booking_rate_limit(
                email_for_limit
            )

        except OperationalError:
            db.session.rollback()

            return jsonify({
                "error": "Rate limiter temporarily unavailable"
            }), 503

        if not allowed:

            response = jsonify({
                "error": "Too many booking attempts"
            })

            response.headers["Retry-After"] = str(
                retry_after
            )

            return response, 429


    idempotency_key = request.headers.get(
        "Idempotency-Key"
    )

    # -----------------------------------------
    # Requests without an idempotency key
    # -----------------------------------------

    if idempotency_key is None:

        try:
            response_data, status_code = process_booking(data)

            if status_code == 201:
                db.session.commit()
            else:
                db.session.rollback()

            return jsonify(response_data), status_code

        except IntegrityError:
            db.session.rollback()

            # A concurrent request may have
            # booked the slot first.
            slot_id = (
                data.get("slot_id")
                if isinstance(data, dict)
                else None
            )

            if isinstance(slot_id, str):
                existing = db.session.query(Booking.id).filter_by(
                    slot_id=slot_id,
                    status="confirmed"
                ).first()

                if existing is not None:
                    return jsonify({
                        "error": "Slot already booked"
                    }), 409

            return jsonify({
                "error": "Unable to create booking"
            }), 500

        except Exception:
            db.session.rollback()

            return jsonify({
                "error": "Unable to create booking"
            }), 500

    # -----------------------------------------
    # Validate the idempotency key
    # -----------------------------------------

    if (
        not idempotency_key
        or len(idempotency_key) > 255
    ):
        return jsonify({
            "error": "Invalid Idempotency-Key"
        }), 400

    # Hash valid JSON consistently.
    # For malformed JSON, hash the raw body.
    if data is None:
        request_hash = hashlib.sha256(
            request.get_data()
        ).hexdigest()
    else:
        request_hash = get_request_hash(data)

    # -----------------------------------------
    # Check for a previously saved response
    # -----------------------------------------

    saved = db.session.get(
        IdempotencyRecord,
        idempotency_key
    )

    if saved is not None:

        if saved.request_hash != request_hash:
            return jsonify({
                "error": (
                    "Idempotency key reused "
                    "with a different body"
                )
            }), 422

        return get_saved_response(saved)

    # End the read-only transaction before
    # attempting to reserve the key.
    db.session.rollback()

    # -----------------------------------------
    # Reserve key, process request and save
    # both results in one transaction
    # -----------------------------------------

    for attempt in range(3):

        try:
            record = IdempotencyRecord(
                key=idempotency_key,
                request_hash=request_hash,
                status_code=0,
                response_body="{}"
            )

            db.session.add(record)

            # Reserves this unique key.
            # Concurrent identical requests cannot
            # both create this database record.
            db.session.flush()

            response_data, status_code = process_booking(
                data
            )

            # Remember the original result,
            # including validation failures.
            record.status_code = status_code
            record.response_body = json.dumps(
                response_data
            )

            db.session.commit()

            return jsonify(response_data), status_code

        except IntegrityError:
            db.session.rollback()

            # Another request might have committed
            # an idempotency record using this key.
            saved = db.session.get(
                IdempotencyRecord,
                idempotency_key
            )

            if saved is not None:

                if saved.request_hash != request_hash:
                    return jsonify({
                        "error": (
                            "Idempotency key reused "
                            "with a different body"
                        )
                    }), 422

                return get_saved_response(saved)

            # A different key may have won the
            # booking race for this slot.
            # Retry so process_booking can return
            # and save the resulting 409 response.
            db.session.rollback()
            continue

        except Exception:
            db.session.rollback()

            return jsonify({
                "error": "Unable to create booking"
            }), 500

    return jsonify({
        "error": "Unable to create booking"
    }), 500

# ------------------------------------------------
# LEVEL 4 - LIST BOOKINGS WITH CURSOR PAGINATION
# GET /bookings
# ------------------------------------------------

@app.route("/bookings", methods=["GET"])
@require_api_key
def list_bookings():

    # Get the patient's email
    email = request.args.get("email")

    if not isinstance(email, str) or not email.strip():
        return jsonify({
            "error": "Email is required"
        }), 400

    email = email.strip().lower()

    # Validate limit: default 10, allowed 1 to 50
    limit_value = request.args.get("limit", "10")

    try:
        if not limit_value.isdigit():
            raise ValueError()

        limit = int(limit_value)

        if limit < 1 or limit > 50:
            raise ValueError()

    except ValueError:
        return jsonify({
            "error": "Invalid limit"
        }), 400

    # Read the optional cursor
    cursor = request.args.get("cursor")

    # Base query for this patient's bookings
    query = db.session.query(Booking).filter(
        func.lower(Booking.email) == email
    )

    if cursor is not None:
        try:
            cursor_time, cursor_id = decode_cursor(cursor)

        except ValueError:
            return jsonify({
                "error": "Invalid cursor"
            }), 400

        # Retrieve only bookings after the cursor
        query = query.filter(
            or_(
                Booking.created_at > cursor_time,
                and_(
                    Booking.created_at == cursor_time,
                    Booking.id > cursor_id
                )
            )
        )

    # Oldest bookings first
    query = query.order_by(
        Booking.created_at.asc(),
        Booking.id.asc()
    )

    # Fetch one extra record to check for a next page
    results = query.limit(limit + 1).all()

    has_more = len(results) > limit

    # Return only the requested number of records
    bookings = results[:limit]

    next_cursor = None

    if has_more and bookings:
        next_cursor = encode_cursor(
            bookings[-1]
        )

    return jsonify({
        "bookings": [
            booking.to_dict()
            for booking in bookings
        ],
        "next_cursor": next_cursor
    }), 200


# ------------------------------------------------
# GET /bookings/<id> - Retrieve a booking
# ------------------------------------------------

@app.route("/bookings/<string:booking_id>", methods=["GET"])
@require_api_key
def get_booking(booking_id):

    # Find a booking using its unique ID
    booking = db.session.get(Booking, booking_id)

    # Return 404 if the booking does not exist
    if booking is None:
        return jsonify({
            "error": "Booking not found"
        }), 404

    # Return the booking details
    return jsonify(booking.to_dict()), 200


# ------------------------------------------------
# DELETE /bookings/<id> - Cancel a booking
# ------------------------------------------------


# ------------------------------------------------
# LEVEL 3 - CANCEL A BOOKING
# DELETE /bookings/<id>
# ------------------------------------------------

@app.route("/bookings/<string:booking_id>", methods=["DELETE"])
@require_api_key
def cancel_booking(booking_id):
    try:
        changed = db.session.query(Booking).filter(
            Booking.id == booking_id, Booking.status == "confirmed"
        ).update({"status": "cancelled"}, synchronize_session=False)
        db.session.commit()
    except OperationalError:
        db.session.rollback()
        return jsonify({"error": "Database temporarily unavailable"}), 503
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Unable to cancel booking"}), 500

    booking = db.session.get(Booking, booking_id)
    if changed == 0:
        if booking is None:
            return jsonify({"error": "Booking not found"}), 404
        return jsonify({"error": "Booking already cancelled"}), 409
    return jsonify(booking.to_dict()), 200


# ------------------------------------------------
# Create tables and enforce booking uniqueness
# ------------------------------------------------

with app.app_context():
    db.create_all()

    # Only one confirmed booking is allowed per slot
    with db.engine.begin() as connection:
        connection.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_confirmed_booking_per_slot
            ON bookings (slot_id)
            WHERE status = 'confirmed'
        """))



from web_ui import register_web_ui
register_web_ui(app)

if __name__ == "__main__":
    app.run(debug=os.getenv("APP_ENV") != "production")
