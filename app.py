import base64, csv, io, os, secrets
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
import requests
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, make_response, redirect, render_template, request, send_from_directory, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image as RLImage
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import os
import smtplib

from email.message import EmailMessage
from email.utils import formataddr


load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///holiday_hub.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "txt"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
CATEGORIES = ["flight", "transport", "hotel", "food", "beach", "activity", "shopping", "kids", "golf", "emergency", "other"]
ICONS = {"flight":"✈", "transport":"🚗", "hotel":"🏨", "food":"🍽", "beach":"🏖", "activity":"🎟", "shopping":"🛍", "kids":"🎈", "golf":"⛳", "emergency":"✚", "other":"📍"}


def clean(value, limit=500):
    return " ".join((value or "").strip().split())[:limit]

def ffloat(value, default=0):
    try: return float(value or default)
    except (TypeError, ValueError): return default

def fdate(value, default=None):
    try: return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError): return default

def ftime(value):
    try: return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError): return None

def valid_url(value):
    try:
        p = urlparse(value)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False

def is_image(document):
    return document.original_name.rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    memberships = db.relationship("TripMember", back_populates="user", cascade="all, delete-orphan")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Trip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    destination = db.Column(db.String(120), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    header_url = db.Column(db.String(600), nullable=False)
    origin = db.Column(db.String(120), default="Dublin")
    currency = db.Column(db.String(8), default="EUR")
    budget = db.Column(db.Float, default=0)
    accommodation = db.Column(db.String(180), default="")
    finalised_at = db.Column(db.DateTime)
    last_finalise_email_at = db.Column(db.DateTime)
    members = db.relationship("TripMember", back_populates="trip", cascade="all, delete-orphan")
    people = db.relationship("FamilyMember", back_populates="trip", cascade="all, delete-orphan")
    events = db.relationship("Event", back_populates="trip", cascade="all, delete-orphan")
    flights = db.relationship("Flight", back_populates="trip", cascade="all, delete-orphan")
    packing_items = db.relationship("PackingItem", back_populates="trip", cascade="all, delete-orphan")
    expenses = db.relationship("Expense", back_populates="trip", cascade="all, delete-orphan")
    documents = db.relationship("Document", back_populates="trip", cascade="all, delete-orphan")
    memories = db.relationship("Memory", back_populates="trip", cascade="all, delete-orphan")
    tasks = db.relationship("Task", back_populates="trip", cascade="all, delete-orphan")
    wishlist = db.relationship("Wishlist", back_populates="trip", cascade="all, delete-orphan")

class TripMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(20), default="member")
    trip = db.relationship("Trip", back_populates="members")
    user = db.relationship("User", back_populates="memberships")
    __table_args__ = (db.UniqueConstraint("trip_id", "user_id"),)

class FamilyMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    name = db.Column(db.String(90), nullable=False)
    member_type = db.Column(db.String(10), default="adult")
    age = db.Column(db.Integer)
    avatar_url = db.Column(db.String(600), default="")
    notes = db.Column(db.String(250), default="")
    trip = db.relationship("Trip", back_populates="people")

class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    title = db.Column(db.String(140), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.Time)
    end_time = db.Column(db.Time)
    category = db.Column(db.String(30), default="activity")
    location = db.Column(db.String(180), default="")
    confirmation = db.Column(db.String(100), default="")
    notes = db.Column(db.Text, default="")
    position = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="planned")
    cost = db.Column(db.Float, default=0)
    booking_url = db.Column(db.String(600), default="")
    assigned_to = db.Column(db.String(180), default="Everyone")
    travel_minutes = db.Column(db.Integer, default=0)
    trip = db.relationship("Trip", back_populates="events")

class Flight(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    flight_number = db.Column(db.String(20), nullable=False)
    flight_date = db.Column(db.Date, nullable=False)
    airline = db.Column(db.String(100), default="")
    departure_airport = db.Column(db.String(120), default="")
    arrival_airport = db.Column(db.String(120), default="")
    scheduled_departure = db.Column(db.String(60), default="")
    scheduled_arrival = db.Column(db.String(60), default="")
    status = db.Column(db.String(40), default="Not checked")
    gate = db.Column(db.String(30), default="")
    terminal = db.Column(db.String(30), default="")
    last_checked = db.Column(db.DateTime)
    raw_json = db.Column(db.Text, default="")
    trip = db.relationship("Trip", back_populates="flights")

class PackingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    owner = db.Column(db.String(80), default="Everyone")
    packed = db.Column(db.Boolean, default=False)
    trip = db.relationship("Trip", back_populates="packing_items")

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(40), default="Other")
    paid_by = db.Column(db.String(80), default="")
    spent_on = db.Column(db.Date, default=date.today)
    trip = db.relationship("Trip", back_populates="expenses")

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    doc_type = db.Column(db.String(30), default="Other")
    stored_name = db.Column(db.String(220), nullable=False)
    original_name = db.Column(db.String(220), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    trip = db.relationship("Trip", back_populates="documents")

class Memory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    memory_date = db.Column(db.Date, default=date.today)
    caption = db.Column(db.Text, default="")
    mood = db.Column(db.String(20), default="😊")
    stored_name = db.Column(db.String(220), nullable=False)
    original_name = db.Column(db.String(220), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    trip = db.relationship("Trip", back_populates="memories")

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    title = db.Column(db.String(140), nullable=False)
    owner = db.Column(db.String(80), default="Everyone")
    completed = db.Column(db.Boolean, default=False)
    trip = db.relationship("Trip", back_populates="tasks")

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trip.id"), nullable=False)
    title = db.Column(db.String(140), nullable=False)
    category = db.Column(db.String(50), default="Place")
    url = db.Column(db.String(600), default="")
    notes = db.Column(db.String(300), default="")
    trip = db.relationship("Trip", back_populates="wishlist")

@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))

def membership(trip_id): return TripMember.query.filter_by(trip_id=trip_id, user_id=current_user.id).first()

def trip_access(owner=False):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapped(trip_id, *args, **kwargs):
            trip = db.session.get(Trip, trip_id)
            member = membership(trip_id)
            if not trip: abort(404)
            if not member or (owner and member.role != "owner"): abort(403)
            return fn(trip, member, *args, **kwargs)
        return wrapped
    return decorator

def stats(trip):
    spent = sum(x.amount for x in trip.expenses)
    packed = sum(1 for x in trip.packing_items if x.packed)
    total = len(trip.packing_items)
    return {
        "spent": spent,
        "remaining": max((trip.budget or 0) - spent, 0),
        "packing_pct": round((packed / total * 100) if total else 0),
        "packed": packed,
        "packing_total": total,
        "days_to_go": (trip.start_date - date.today()).days,
        "duration": (trip.end_date - trip.start_date).days + 1,
    }

def grouped_events(trip):
    grouped = defaultdict(list)
    for event in sorted(trip.events, key=lambda x: (x.event_date, x.position, x.event_time or datetime.min.time())):
        grouped[event.event_date].append(event)
    return dict(grouped)

def todays_events(trip):
    target = date.today() if trip.start_date <= date.today() <= trip.end_date else trip.start_date
    return sorted([x for x in trip.events if x.event_date == target], key=lambda x: (x.event_time or datetime.min.time(), x.position)), target

def warnings_for(trip):
    warnings = []
    for day, events in grouped_events(trip).items():
        timed = [x for x in events if x.event_time]
        for first, second in zip(timed, timed[1:]):
            first_end = first.end_time or first.event_time
            gap = (datetime.combine(day, second.event_time) - datetime.combine(day, first_end)).total_seconds() / 60
            if gap < 0: warnings.append(f"{day:%a %d %b}: {first.title} overlaps {second.title}.")
            elif second.travel_minutes and gap < second.travel_minutes: warnings.append(f"{day:%a %d %b}: only {int(gap)} minutes before {second.title}; travel needs {second.travel_minutes}.")
    return warnings

@app.context_processor
def helpers(): return {"ICONS": ICONS, "CATEGORIES": CATEGORIES, "today": date.today(), "is_image": is_image}

@app.after_request
def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    return response


def verification_token(user): return serializer.dumps({"uid": user.id, "email": user.email}, salt="verify-email")

def send_mail(
    to_email: str,
    subject: str,
    html: str,
    text_body: str,
    attachments: list[dict] | None = None,
):
    """Send email using Gmail SMTP."""

    smtp_server = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("MAIL_PORT", "587"))

    username = os.getenv("MAIL_USERNAME", "").strip()
    app_password = os.getenv("MAIL_PASSWORD", "").replace(" ", "").strip()
    from_name = os.getenv("MAIL_FROM_NAME", "Holiday Hub").strip()

    if not username:
        raise RuntimeError("MAIL_USERNAME is not configured")

    if not app_password:
        raise RuntimeError("MAIL_PASSWORD is not configured")

    if not to_email or "@" not in to_email:
        raise ValueError("A valid recipient email address is required")

    message = EmailMessage()

    message["From"] = formataddr((from_name, username))
    message["To"] = to_email
    message["Subject"] = subject

    # Plain-text alternative
    message.set_content(text_body)

    # HTML version
    message.add_alternative(html, subtype="html")

    # Attachments arrive from your Finalize Trip function as Base64.
    for attachment in attachments or []:
        encoded_content = attachment.get("content")
        filename = attachment.get("filename", "attachment.pdf")

        if not encoded_content:
            continue

        file_bytes = base64.b64decode(encoded_content)

        message.add_attachment(
            file_bytes,
            maintype="application",
            subtype="pdf",
            filename=filename,
        )

    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(username, app_password)
        server.send_message(message)

    return True
def verification_email_html(user, link):
    return render_template("emails/verify.html", user=user, verify_link=link)

def send_verification(user):
    link = url_for("verify_email", token=verification_token(user), _external=True)
    send_mail(user.email, "Verify your Holiday Hub email", verification_email_html(user, link), f"Verify your email: {link}")

@app.route("/")
def landing(): return redirect(url_for("dashboard")) if current_user.is_authenticated else render_template("landing.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated: return redirect(url_for("dashboard"))
    if request.method == "POST":
        name = clean(request.form.get("name"), 80)
        email = clean(request.form.get("email"), 254).lower()
        password = request.form.get("password", "")
        if not name or "@" not in email or len(password) < 10:
            flash("Use a valid email and a password of at least 10 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email is already registered.", "error")
        else:
            user = User(name=name, email=email)
            user.set_password(password)
            db.session.add(user); db.session.commit(); login_user(user)
            try:
                send_verification(user)
                flash("Account created. Check your inbox to verify your email.", "success")
            except Exception:
                flash("Account created, but email is not configured yet. You can resend verification from Settings.", "warning")
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="register")

@app.route("/verify-email/<token>")
def verify_email(token):
    try: data = serializer.loads(token, salt="verify-email", max_age=86400)
    except SignatureExpired:
        flash("That verification link has expired.", "error"); return redirect(url_for("login"))
    except BadSignature:
        abort(400)
    user = db.session.get(User, int(data["uid"]))
    if not user or user.email != data["email"]: abort(400)
    user.email_verified = True; db.session.commit()
    flash("Email verified. Your account is now protected.", "success")
    return redirect(url_for("dashboard"))

@app.post("/account/resend-verification")
@login_required
def resend_verification():
    if current_user.email_verified:
        flash("Your email is already verified.", "success")
    else:
        try: send_verification(current_user); flash("Verification email sent.", "success")
        except Exception as exc: flash(f"Email could not be sent: {exc}", "error")
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=clean(request.form.get("email"), 254).lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(url_for("dashboard"))
        flash("Incorrect email or password.", "error")
    return render_template("auth.html", mode="login")

@app.post("/logout")
@login_required
def logout(): logout_user(); return redirect(url_for("landing"))

@app.route("/home")
@login_required
def dashboard():
    trips = [m.trip for m in current_user.memberships]
    return render_template("dashboard.html", trips=trips)

@app.route("/trips/new", methods=["GET", "POST"])
@login_required
def new_trip():
    if request.method == "POST":
        header_url = clean(request.form.get("header_url"), 600)
        start = fdate(request.form.get("start_date")); end = fdate(request.form.get("end_date"))
        if not valid_url(header_url): flash("A valid header photo URL is required.", "error")
        elif not start or not end or end < start: flash("Choose valid trip dates.", "error")
        else:
            trip = Trip(name=clean(request.form.get("name"),120), destination=clean(request.form.get("destination"),120), start_date=start, end_date=end, header_url=header_url, origin=clean(request.form.get("origin"),120) or "Dublin", budget=ffloat(request.form.get("budget")), accommodation=clean(request.form.get("accommodation"),180))
            db.session.add(trip); db.session.flush(); db.session.add(TripMember(trip=trip, user=current_user, role="owner")); db.session.commit()
            return redirect(url_for("trip_home", trip_id=trip.id))
    return render_template("trip_form.html")

@app.route("/trips/<int:trip_id>")
@trip_access()
def trip_home(trip, member):
    events, focus_date = todays_events(trip)
    upcoming = sorted([x for x in trip.events if x.event_date >= date.today()], key=lambda x:(x.event_date,x.event_time or datetime.min.time()))[:5]
    return render_template("trip_home.html", trip=trip, stats=stats(trip), today_events=events, focus_date=focus_date, upcoming=upcoming, warnings=warnings_for(trip))

@app.route("/trips/<int:trip_id>/journey", methods=["GET", "POST"])
@trip_access()
def journey(trip, member):
    if request.method == "POST":
        event = Event(trip=trip, title=clean(request.form.get("title"),140), event_date=fdate(request.form.get("event_date"),trip.start_date), event_time=ftime(request.form.get("event_time")), end_time=ftime(request.form.get("end_time")), category=request.form.get("category","activity"), location=clean(request.form.get("location"),180), confirmation=clean(request.form.get("confirmation"),100), notes=clean(request.form.get("notes"),1000), status=request.form.get("status","planned"), cost=ffloat(request.form.get("cost")), booking_url=clean(request.form.get("booking_url"),600), assigned_to=clean(request.form.get("assigned_to"),180) or "Everyone", travel_minutes=int(ffloat(request.form.get("travel_minutes"))), position=len(trip.events))
        if event.title: db.session.add(event); db.session.commit(); flash("Activity added.", "success")
        return redirect(url_for("journey", trip_id=trip.id))
    return render_template("journey.html", trip=trip, grouped=grouped_events(trip), warnings=warnings_for(trip))

@app.post("/trips/<int:trip_id>/events/<int:event_id>/delete")
@trip_access()
def delete_event(trip, member, event_id):
    event = db.session.get(Event, event_id)
    if not event or event.trip_id != trip.id: abort(404)
    db.session.delete(event); db.session.commit(); return redirect(url_for("journey", trip_id=trip.id))

@app.post("/trips/<int:trip_id>/journey/reorder")
@trip_access()
def reorder(trip, member):
    for row in (request.get_json(silent=True) or {}).get("items", []):
        event = db.session.get(Event, int(row.get("id",0)))
        if event and event.trip_id == trip.id:
            event.position = int(row.get("position",0)); event.event_date = fdate(row.get("date"), event.event_date)
    db.session.commit(); return jsonify(ok=True)

@app.route("/trips/<int:trip_id>/flights", methods=["POST"])
@trip_access()
def add_flight(trip, member):
    number = clean(request.form.get("flight_number"),20).upper().replace(" ","")
    flight_date = fdate(request.form.get("flight_date"), trip.start_date)
    if number:
        db.session.add(Flight(trip=trip, flight_number=number, flight_date=flight_date)); db.session.commit(); flash("Flight added. Use Refresh status to retrieve live data.", "success")
    return redirect(url_for("journey", trip_id=trip.id) + "#flights")

def fetch_flight_data(flight):
    key = os.getenv("AVIATIONSTACK_API_KEY", "")
    if not key: raise RuntimeError("AVIATIONSTACK_API_KEY is not configured")
    response = requests.get("https://api.aviationstack.com/v1/flights", params={"access_key":key, "flight_iata":flight.flight_number, "flight_date":flight.flight_date.isoformat(), "limit":1}, timeout=25)
    response.raise_for_status()
    rows = response.json().get("data", [])
    if not rows: raise RuntimeError("No matching flight was returned")
    row = rows[0]
    dep, arr = row.get("departure") or {}, row.get("arrival") or {}
    flight.airline = (row.get("airline") or {}).get("name","")
    flight.departure_airport = dep.get("airport","")
    flight.arrival_airport = arr.get("airport","")
    flight.scheduled_departure = dep.get("scheduled","")
    flight.scheduled_arrival = arr.get("scheduled","")
    flight.status = row.get("flight_status") or "Unknown"
    flight.gate = dep.get("gate") or ""
    flight.terminal = dep.get("terminal") or ""
    flight.last_checked = datetime.utcnow()
    flight.raw_json = str(row)[:10000]

@app.post("/trips/<int:trip_id>/flights/<int:flight_id>/refresh")
@trip_access()
def refresh_flight(trip, member, flight_id):
    flight = db.session.get(Flight, flight_id)
    if not flight or flight.trip_id != trip.id: abort(404)
    try: fetch_flight_data(flight); db.session.commit(); flash("Flight status refreshed.", "success")
    except Exception as exc: flash(f"Flight data unavailable: {exc}", "error")
    return redirect(url_for("journey", trip_id=trip.id) + "#flights")

@app.post("/trips/<int:trip_id>/flights/<int:flight_id>/delete")
@trip_access()
def delete_flight(trip, member, flight_id):
    flight = db.session.get(Flight, flight_id)
    if not flight or flight.trip_id != trip.id: abort(404)
    db.session.delete(flight); db.session.commit(); return redirect(url_for("journey", trip_id=trip.id) + "#flights")

@app.route("/trips/<int:trip_id>/explore", methods=["GET", "POST"])
@trip_access()
def explore(trip, member):
    if request.method == "POST":
        item = Wishlist(trip=trip, title=clean(request.form.get("title"),140), category=clean(request.form.get("category"),50) or "Place", url=clean(request.form.get("url"),600), notes=clean(request.form.get("notes"),300))
        if item.title: db.session.add(item); db.session.commit()
        return redirect(url_for("explore", trip_id=trip.id))
    return render_template("explore.html", trip=trip)

@app.post("/trips/<int:trip_id>/wishlist/<int:item_id>/delete")
@trip_access()
def delete_wishlist(trip, member, item_id):
    item = db.session.get(Wishlist,item_id)
    if not item or item.trip_id != trip.id: abort(404)
    db.session.delete(item); db.session.commit(); return redirect(url_for("explore", trip_id=trip.id))

@app.route("/trips/<int:trip_id>/family", methods=["GET", "POST"])
@trip_access()
def family(trip, member):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "person":
            kind = request.form.get("member_type","adult")
            person = FamilyMember(trip=trip, name=clean(request.form.get("name"),90), member_type=kind, age=None if kind=="adult" else int(ffloat(request.form.get("age"))), avatar_url=clean(request.form.get("avatar_url"),600), notes=clean(request.form.get("notes"),250))
            if person.name: db.session.add(person)
        elif action == "packing":
            db.session.add(PackingItem(trip=trip, label=clean(request.form.get("label"),120), owner=clean(request.form.get("owner"),80) or "Everyone"))
        elif action == "expense":
            db.session.add(Expense(trip=trip, label=clean(request.form.get("label"),120), amount=ffloat(request.form.get("amount")), category=clean(request.form.get("category"),40) or "Other", paid_by=clean(request.form.get("paid_by"),80), spent_on=fdate(request.form.get("spent_on"),date.today())))
        elif action == "task":
            db.session.add(Task(trip=trip, title=clean(request.form.get("title"),140), owner=clean(request.form.get("owner"),80) or "Everyone"))
        db.session.commit(); return redirect(url_for("family", trip_id=trip.id))
    return render_template("family.html", trip=trip, stats=stats(trip))

@app.post("/trips/<int:trip_id>/family/<kind>/<int:item_id>/toggle")
@trip_access()
def toggle_family_item(trip, member, kind, item_id):
    model = PackingItem if kind == "packing" else Task
    item = db.session.get(model, item_id)
    if not item or item.trip_id != trip.id: abort(404)
    if kind == "packing": item.packed = not item.packed
    else: item.completed = not item.completed
    db.session.commit(); return redirect(url_for("family", trip_id=trip.id))

@app.post("/trips/<int:trip_id>/family/person/<int:item_id>/delete")
@trip_access(owner=True)
def delete_person(trip, member, item_id):
    item = db.session.get(FamilyMember,item_id)
    if not item or item.trip_id != trip.id: abort(404)
    db.session.delete(item); db.session.commit(); return redirect(url_for("family", trip_id=trip.id))

@app.route("/trips/<int:trip_id>/documents", methods=["GET", "POST"])
@trip_access()
def documents(trip, member):
    if request.method == "POST":
        file = request.files.get("file")
        if file and "." in file.filename and file.filename.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS:
            original = secure_filename(file.filename); stored = f"{secrets.token_hex(12)}-{original}"; file.save(UPLOAD_DIR/stored)
            db.session.add(Document(trip=trip, title=clean(request.form.get("title"),120) or original, doc_type=clean(request.form.get("doc_type"),30) or "Other", stored_name=stored, original_name=original)); db.session.commit()
        return redirect(url_for("documents", trip_id=trip.id))
    return render_template("documents.html", trip=trip)

@app.route("/trips/<int:trip_id>/documents/<int:document_id>")
@trip_access()
def document_file(trip, member, document_id):
    document = db.session.get(Document,document_id)
    if not document or document.trip_id != trip.id: abort(404)
    return send_from_directory(UPLOAD_DIR, document.stored_name, as_attachment=False, download_name=document.original_name)

@app.route("/trips/<int:trip_id>/memories", methods=["GET", "POST"])
@trip_access()
def memories(trip, member):
    if request.method == "POST":
        file = request.files.get("photo")
        if file and "." in file.filename and file.filename.rsplit(".",1)[1].lower() in IMAGE_EXTENSIONS:
            original=secure_filename(file.filename); stored=f"memory-{secrets.token_hex(12)}-{original}"; file.save(UPLOAD_DIR/stored)
            db.session.add(Memory(trip=trip, title=clean(request.form.get("title"),120) or "Holiday memory", memory_date=fdate(request.form.get("memory_date"),date.today()), caption=clean(request.form.get("caption"),1500), mood=clean(request.form.get("mood"),20) or "😊", stored_name=stored, original_name=original)); db.session.commit()
        return redirect(url_for("memories", trip_id=trip.id))
    return render_template("memories.html", trip=trip)

@app.route("/trips/<int:trip_id>/memories/<int:memory_id>/photo")
@trip_access()
def memory_photo(trip, member, memory_id):
    memory = db.session.get(Memory,memory_id)
    if not memory or memory.trip_id != trip.id: abort(404)
    return send_from_directory(UPLOAD_DIR,memory.stored_name)

@app.post("/trips/<int:trip_id>/memories/<int:memory_id>/delete")
@trip_access()
def delete_memory(trip, member, memory_id):
    memory=db.session.get(Memory,memory_id)
    if not memory or memory.trip_id != trip.id: abort(404)
    (UPLOAD_DIR/memory.stored_name).unlink(missing_ok=True); db.session.delete(memory); db.session.commit(); return redirect(url_for("memories",trip_id=trip.id))

@app.route("/trips/<int:trip_id>/settings", methods=["GET", "POST"])
@trip_access(owner=True)
def settings(trip, member):
    if request.method == "POST":
        header_url=clean(request.form.get("header_url"),600)
        if not valid_url(header_url): flash("Enter a valid header photo URL.","error")
        else:
            trip.name=clean(request.form.get("name"),120); trip.destination=clean(request.form.get("destination"),120); trip.header_url=header_url; trip.origin=clean(request.form.get("origin"),120); trip.accommodation=clean(request.form.get("accommodation"),180); trip.budget=ffloat(request.form.get("budget")); db.session.commit(); flash("Trip updated.","success")
            return redirect(url_for("settings",trip_id=trip.id))
    return render_template("settings.html",trip=trip)


def build_trip_pdf(trip):
    output=io.BytesIO(); doc=SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=12*mm,leftMargin=12*mm,topMargin=12*mm,bottomMargin=12*mm)
    styles=getSampleStyleSheet(); styles.add(ParagraphStyle(name="Hero",parent=styles["Title"],fontSize=28,leading=32,textColor=colors.HexColor("#12372f"),alignment=TA_CENTER,spaceAfter=10))
    story=[Paragraph(trip.name,styles["Hero"]),Paragraph(f"{trip.destination} · {trip.start_date:%d %B %Y} – {trip.end_date:%d %B %Y}",styles["Heading2"]),Spacer(1,8*mm)]
    s=stats(trip)
    overview=[["Travellers",str(len(trip.people))],["Activities",str(len(trip.events))],["Budget",f"{trip.currency} {trip.budget:,.2f}"],["Spent",f"{trip.currency} {s['spent']:,.2f}"],["Packing",f"{s['packing_pct']}%"]]
    table=Table(overview,colWidths=[45*mm,65*mm]); table.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eaf8f4")),("TEXTCOLOR",(0,0),(0,-1),colors.HexColor("#0d4f43")),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),0.5,colors.HexColor("#cbd5e1")),("PADDING",(0,0),(-1,-1),8)])); story += [table,PageBreak(),Paragraph("Journey",styles["Hero"])]
    rows=[["Date","Time","Activity","Location","Traveller"]]
    for e in sorted(trip.events,key=lambda x:(x.event_date,x.event_time or datetime.min.time(),x.position)):
        rows.append([e.event_date.strftime("%a %d %b"),e.event_time.strftime("%H:%M") if e.event_time else "Any time",e.title,e.location,e.assigned_to])
    table=Table(rows,repeatRows=1,colWidths=[30*mm,22*mm,75*mm,75*mm,42*mm]); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0f766e")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#d8e2df")),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8),("PADDING",(0,0),(-1,-1),5)])); story.append(table)
    for document in trip.documents:
        if is_image(document):
            path=UPLOAD_DIR/document.stored_name
            if path.exists():
                story += [PageBreak(),Paragraph(document.title,styles["Hero"]),Spacer(1,3*mm)]
                try: story.append(RLImage(str(path),width=245*mm,height=155*mm,kind="proportional"))
                except Exception: story.append(Paragraph("Image could not be rendered.",styles["BodyText"]))
    doc.build(story); output.seek(0); return output.getvalue()

@app.route("/trips/<int:trip_id>/print")
@trip_access()
def overview_print(trip, member):
    return render_template("overview_print.html",trip=trip,grouped=grouped_events(trip),stats=stats(trip),print_date=date.today())

@app.route("/trips/<int:trip_id>/pdf")
@trip_access()
def trip_pdf(trip, member):
    data=build_trip_pdf(trip); response=make_response(data); response.headers["Content-Type"]="application/pdf"; response.headers["Content-Disposition"]=f'attachment; filename="{secure_filename(trip.name)}-holiday-book.pdf"'; return response

@app.post("/trips/<int:trip_id>/finalize")
@trip_access(owner=True)
def finalize_trip(trip, member):
    if not current_user.email_verified:
        flash(
            "Verify your registered email before finalising a trip.",
            "error",
        )
        return redirect(url_for("settings", trip_id=trip.id))

    if request.form.get("confirm_phrase", "").strip() != "FINALIZE":
        flash(
            "Type FINALIZE exactly to confirm.",
            "error",
        )
        return redirect(url_for("settings", trip_id=trip.id))

    if request.form.get("confirm_email", "").strip() != current_user.email:
        flash(
            "The confirmation email must exactly match your registered account email.",
            "error",
        )
        return redirect(url_for("settings", trip_id=trip.id))

    if not request.form.get("acknowledge"):
        flash(
            "Tick the final confirmation box.",
            "error",
        )
        return redirect(url_for("settings", trip_id=trip.id))

    if (
        trip.last_finalise_email_at
        and datetime.utcnow() - trip.last_finalise_email_at
        < timedelta(minutes=15)
    ):
        flash(
            "A final trip email was sent recently. "
            "Please wait 15 minutes before sending again.",
            "error",
        )
        return redirect(url_for("settings", trip_id=trip.id))

    pdf = build_trip_pdf(trip)

    html = render_template(
        "emails/final_trip.html",
        user=current_user,
        trip=trip,
        stats=stats(trip),
        events=sorted(
            trip.events,
            key=lambda event: (
                event.event_date,
                event.event_time or datetime.min.time(),
            ),
        ),
    )

    attachment = {
        "content": base64.b64encode(pdf).decode("ascii"),
        "filename": (
            f"{secure_filename(trip.name)}-holiday-book.pdf"
        ),
    }

    try:
        send_mail(
            to_email=current_user.email,
            subject=f"Your final {trip.name} holiday plan",
            html=html,
            text_body=(
                f"Your final holiday plan for {trip.name} "
                "is attached."
            ),
            attachments=[attachment],
        )

        trip.finalised_at = datetime.utcnow()
        trip.last_finalise_email_at = datetime.utcnow()
        db.session.commit()

        flash(
            f"Final holiday pack sent only to "
            f"{current_user.email}.",
            "success",
        )

    except Exception:
        app.logger.exception(
            "Failed to send final trip email for trip %s",
            trip.id,
        )

        flash(
            "The final holiday pack could not be emailed. "
            "Check your Resend settings and try again.",
            "error",
        )

    return redirect(url_for("settings", trip_id=trip.id))

@app.errorhandler(403)
def forbidden(_):
    return render_template(
        "error.html",
        code=403,
        message="You do not have access to that trip.",
    ), 403


@app.errorhandler(404)
def missing(_):
    return render_template(
        "error.html",
        code=404,
        message="That page could not be found.",
    ), 404


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "true").lower() == "true"
    )