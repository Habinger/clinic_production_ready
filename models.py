
from datetime import datetime, timezone
from database import db


class Slot(db.Model):
    __tablename__ = "slots"

    id = db.Column(
        db.String(50),
        primary_key=True
    )

    provider = db.Column(
        db.String(100),
        nullable=False
    )

    start = db.Column(
        db.String(30),
        nullable=False
    )

    end = db.Column(
        db.String(30),
        nullable=False
    )

    def to_dict(self):
        # Check whether this slot has a confirmed booking
        confirmed_booking = db.session.query(Booking.id).filter_by(
            slot_id=self.id,
            status="confirmed"
        ).first()

        return {
            "id": self.id,
            "provider": self.provider,
            "start": self.start,
            "end": self.end,
            "available": confirmed_booking is None
        }


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(
        db.String(36),
        primary_key=True
    )

    slot_id = db.Column(
        db.String(50),
        db.ForeignKey("slots.id"),
        nullable=False
    )

    name = db.Column(
        db.String(100),
        nullable=False
    )

    email = db.Column(
        db.String(254),
        nullable=False
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        default="confirmed"
    )

    created_at = db.Column(
        db.String(30),
        nullable=False,
        default=lambda: datetime.now(
            timezone.utc
        ).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
    )

    def to_dict(self):
        return {
            "id": self.id,
            "slot_id": self.slot_id,
            "name": self.name,
            "email": self.email,
            "status": self.status,
            "created_at": self.created_at
        }

class IdempotencyRecord(db.Model):
    __tablename__ = "idempotency_records"

    key = db.Column(
        db.String(255),
        primary_key=True
    )

    request_hash = db.Column(
        db.String(64),
        nullable=False
    )

    status_code = db.Column(
        db.Integer,
        nullable=False
    )

    response_body = db.Column(
        db.Text,
        nullable=False
    )

# ------------------------------------------------
# LEVEL 5 - RATE LIMIT ATTEMPTS
# ------------------------------------------------

class RateLimitAttempt(db.Model):
    __tablename__ = "rate_limit_attempts"

    id = db.Column(
        db.Integer,
        primary_key=True,
        autoincrement=True
    )

    email = db.Column(
        db.String(254),
        nullable=False
    )

    attempted_at_ms = db.Column(
        db.BigInteger,
        nullable=False
    )

    __table_args__ = (
        db.Index(
            "ix_rate_attempt_email_time",
            "email",
            "attempted_at_ms"
        ),
    )
