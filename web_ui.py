"""Same-origin patient interface for the existing, API-key protected Flask API.

register_web_ui(app) once during app startup. Requests are forwarded internally to
existing API endpoints, preserving authentication, validation, idempotency and limits.
The API key is never delivered to the patient's browser.
"""
import os
import secrets
from flask import jsonify, render_template, request, session, make_response


def register_web_ui(app):
    session_secret = os.getenv('WEB_SESSION_SECRET')
    if not session_secret or len(session_secret) < 32:
        raise RuntimeError('Set WEB_SESSION_SECRET to a random string of at least 32 characters in .env')
    app.secret_key = session_secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', '1' if os.getenv('APP_ENV') == 'production' else '0') == '1',
    )

    def internal_api(method, path, json_body=None, extra_headers=None):
        headers = {'X-API-Key': os.environ['API_KEY']}
        if extra_headers:
            headers.update(extra_headers)
        # Internal dispatch; no browser-to-API call and no network round trip.
        with app.test_client() as internal:
            response = internal.open(path, method=method, json=json_body, headers=headers)
        outward = make_response(response.get_data(), response.status_code)
        outward.headers['Content-Type'] = response.headers.get('Content-Type', 'application/json')
        if response.headers.get('Retry-After'):
            outward.headers['Retry-After'] = response.headers['Retry-After']
        outward.headers['Cache-Control'] = 'no-store'
        return outward

    @app.get('/')
    def patient_home():
        token = secrets.token_urlsafe(32)
        session['booking_csrf'] = token
        response = make_response(render_template('index.html', csrf_token=token))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response

    @app.get('/web/slots')
    def web_slots():
        # Only forward the optional provider query, which the API already supports.
        from urllib.parse import urlencode
        provider = request.args.get('provider')
        path = '/slots' + ('?' + urlencode({'provider': provider}) if provider is not None else '')
        return internal_api('GET', path)

    @app.post('/web/bookings')
    def web_bookings():
        expected = session.get('booking_csrf')
        supplied = request.headers.get('X-CSRF-Token', '')
        if not expected or not secrets.compare_digest(supplied, expected):
            return jsonify({'error': 'Invalid form session. Refresh the page and try again.'}), 403

        if request.content_length is not None and request.content_length > 8192:
            return jsonify({'error': 'Booking request is too large'}), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({'error': 'Invalid JSON body'}), 400

        # Whitelist exactly the API's expected booking fields.
        clean = {key: body[key] for key in ('slot_id', 'name', 'email') if key in body}
        idempotency_key = request.headers.get('Idempotency-Key', '')
        if not idempotency_key or len(idempotency_key) > 255:
            return jsonify({'error': 'Missing or invalid booking request key'}), 400
        return internal_api('POST', '/bookings', clean, {'Idempotency-Key': idempotency_key})
