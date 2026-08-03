from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from flask import (
    Flask,
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    inspect,
    insert,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.pool import NullPool
from werkzeug.middleware.proxy_fix import ProxyFix

from pdf_builder import build_form6_pdf, build_simple_request_pdf

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
LOCAL_DB_PATH = INSTANCE_DIR / "spnhs_requests.db"
SECRET_PATH = INSTANCE_DIR / ".secret_key"


def running_on_vercel() -> bool:
    return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))


def normalize_database_url(raw_url: str) -> str:
    """Convert common Postgres URLs into SQLAlchemy's Psycopg 3 URL format."""
    value = raw_url.strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def configured_database_url() -> str | None:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if raw_url:
        return normalize_database_url(raw_url)

    # Local development keeps the familiar SQLite workflow. Vercel must use
    # DATABASE_URL so records are stored persistently in Neon Postgres.
    if running_on_vercel():
        return None

    INSTANCE_DIR.mkdir(exist_ok=True)
    return f"sqlite+pysqlite:///{LOCAL_DB_PATH.as_posix()}"


def load_secret_key() -> str:
    env_secret = os.getenv("SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    if running_on_vercel():
        # The app remains deployable, but the README requires replacing this
        # value with a long Vercel environment variable before actual use.
        return "CHANGE-ME-IN-VERCEL-ENVIRONMENT-VARIABLES"

    INSTANCE_DIR.mkdir(exist_ok=True)
    if SECRET_PATH.exists():
        return SECRET_PATH.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


app = Flask(__name__, static_folder="public", static_url_path="")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=running_on_vercel(),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    PREFERRED_URL_SCHEME="https" if running_on_vercel() else "http",
)

REQUEST_TYPES = {
    "FORM_6": "Form 6 - Application for Leave",
    "COE": "Certificate of Employment",
    "SERVICE_RECORD": "Service Record",
}

STATUS_OPTIONS = [
    "Submitted",
    "For Principal Approval",
    "Submitted to SDO Records",
    "Approved Returned to School",
    "Disapproved Returned to School",
]

LEAVE_TYPES = [
    "Vacation Leave",
    "Mandatory/Forced Leave",
    "Sick Leave",
    "Maternity Leave",
    "Paternity Leave",
    "Special Privilege Leave",
    "Solo Parent Leave",
    "Study Leave",
    "10-Day VAWC Leave",
    "Rehabilitation Privilege",
    "Special Leave Benefits for Women",
    "Special Emergency (Calamity) Leave",
    "Adoption Leave",
    "Others",
]

FORM_VARIANTS = {
    "regular": "Regular / Front Form",
    "monetization": "Monetization of Leave Credits",
    "terminal": "Terminal Leave",
    "more_than_60_days": "Leave for More Than 60 Days",
}

FORM6_KEYS = [
    "middle_name",
    "date_filing",
    "position",
    "salary",
    "leave_type",
    "other_leave_type",
    "leave_detail_mode",
    "leave_detail_text",
    "study_purpose",
    "other_purpose",
    "working_days",
    "inclusive_dates",
    "commutation",
    "form_variant",
    "credits_as_of",
    "vacation_total",
    "sick_total",
    "vacation_less",
    "sick_less",
    "vacation_balance",
    "sick_balance",
    "recommendation",
    "recommendation_reason",
    "approved_with_pay",
    "approved_without_pay",
    "approved_others",
    "disapproved_reason",
    "approval_date",
]

# SQLAlchemy Core schema supports both Neon Postgres and local SQLite.
metadata = MetaData()
id_type = BigInteger().with_variant(Integer, "sqlite")

users_table = Table(
    "users",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("username", String(150), unique=True, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("full_name", Text, nullable=False),
    Column("created_at", String(32), nullable=False),
)

settings_table = Table(
    "settings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("school_name", Text, nullable=False),
    Column("school_subtitle", Text, nullable=False),
    Column("division", Text, nullable=False),
    Column("region", Text),
    Column("address", Text),
    Column("records_email", Text),
    Column("records_contact", Text),
    CheckConstraint("id = 1", name="settings_single_row"),
)

requests_table = Table(
    "requests",
    metadata,
    Column("id", id_type, primary_key=True, autoincrement=True),
    Column("tracking_no", String(80), unique=True, nullable=False, index=True),
    Column("request_type", String(40), nullable=False, index=True),
    Column("surname", Text, nullable=False),
    Column("first_name", Text, nullable=False),
    Column("middle_initial", Text),
    Column("first_day_service", String(20)),
    Column("contact_no", Text),
    Column("form_data", Text, nullable=False, server_default="{}"),
    Column("status", String(50), nullable=False, server_default="Submitted", index=True),
    Column("admin_remarks", Text),
    Column("submitted_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)

_engine: Engine | None = None
_database_initialized = False
_database_lock = Lock()


class DatabaseNotConfigured(RuntimeError):
    pass


def get_engine() -> Engine:
    global _engine
    if _engine is not None:
        return _engine

    database_url = configured_database_url()
    if not database_url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is missing. Connect a Neon Postgres database to this Vercel project, "
            "then redeploy the application."
        )

    options: dict[str, Any] = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("postgresql+psycopg://"):
        # A serverless function should not keep a large local connection pool.
        # Use Neon's pooled DATABASE_URL and open only the connection needed for
        # the current request.
        options.update(
            poolclass=NullPool,
            connect_args={"connect_timeout": 10, "prepare_threshold": None},
        )
    else:
        options.update(connect_args={"check_same_thread": False})

    _engine = create_engine(database_url, **options)
    return _engine


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"pbkdf2_sha256$260000${salt.hex()}${digest.hex()}"


def password_verify(stored: str, password: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        ).hex()
        return hmac.compare_digest(actual, digest_hex)
    except (ValueError, TypeError):
        return False


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def migrate_existing_schema(engine: Engine) -> None:
    """Apply small, safe migrations for databases created by earlier versions."""
    inspector = inspect(engine)
    if "requests" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("requests")}
    if "contact_no" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE requests ADD COLUMN contact_no TEXT"))


def seed_database(engine: Engine) -> None:
    admin_username = os.getenv("ADMIN_USERNAME", "admin").strip().lower() or "admin"
    admin_password = os.getenv("ADMIN_PASSWORD", "SPNHS2026!")
    admin_name = os.getenv(
        "ADMIN_FULL_NAME", "SPNHS-SHS Records Administrator"
    ).strip() or "SPNHS-SHS Records Administrator"

    # Separate transactions make concurrent serverless cold starts harmless: a
    # unique-key race simply means another instance already created the row.
    try:
        with engine.begin() as connection:
            existing_user = connection.execute(
                select(users_table.c.id).where(
                    func.lower(users_table.c.username) == admin_username
                )
            ).first()
            if existing_user is None:
                connection.execute(
                    insert(users_table).values(
                        username=admin_username,
                        password_hash=password_hash(admin_password),
                        full_name=admin_name,
                        created_at=now_iso(),
                    )
                )
    except IntegrityError:
        pass

    try:
        with engine.begin() as connection:
            existing_settings = connection.execute(
                select(settings_table.c.id).where(settings_table.c.id == 1)
            ).first()
            if existing_settings is None:
                connection.execute(
                    insert(settings_table).values(
                        id=1,
                        school_name="Sangley Point National High School",
                        school_subtitle="Senior High School",
                        division="Schools Division Office of Cavite City",
                        region="Region IV-A CALABARZON",
                        address="Sangley Point, Cavite City",
                        records_email="",
                        records_contact="",
                    )
                )
    except IntegrityError:
        pass


def ensure_database() -> None:
    global _database_initialized
    if _database_initialized:
        return
    with _database_lock:
        if _database_initialized:
            return
        engine = get_engine()
        metadata.create_all(engine)
        migrate_existing_schema(engine)
        seed_database(engine)
        _database_initialized = True


def get_db() -> Connection:
    ensure_database()
    if "db" not in g:
        g.db = get_engine().connect()
    return g.db


@app.teardown_appcontext
def close_db(_: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> None:
    supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(400, "Invalid or expired form token. Refresh the page and try again.")


@app.context_processor
def inject_globals() -> dict[str, Any]:
    return {
        "REQUEST_TYPES": REQUEST_TYPES,
        "STATUS_OPTIONS": STATUS_OPTIONS,
        "LEAVE_TYPES": LEAVE_TYPES,
        "FORM_VARIANTS": FORM_VARIANTS,
        "csrf_token": csrf_token,
        "current_year": date.today().year,
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("admin_login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def json_load(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def generate_tracking_no(request_type: str) -> str:
    prefix = {"FORM_6": "F6", "COE": "COE", "SERVICE_RECORD": "SR"}[request_type]
    db = get_db()
    for _ in range(20):
        code = f"{prefix}-{date.today():%Y%m%d}-{secrets.token_hex(2).upper()}"
        exists = db.execute(
            select(requests_table.c.id).where(requests_table.c.tracking_no == code)
        ).first()
        if exists is None:
            return code
    raise RuntimeError("Unable to generate a unique tracking number")


def display_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return value


def form_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%m/%d/%Y")
    except ValueError:
        return value


@app.template_filter("display_date")
def display_date_filter(value: str | None) -> str:
    return display_date(value)


def detect_form_variant(form_data: dict[str, Any]) -> str:
    other_purpose = str(form_data.get("other_purpose", ""))
    if other_purpose == "Monetization of Leave Credits":
        return "monetization"
    if other_purpose == "Terminal Leave":
        return "terminal"
    try:
        if float(str(form_data.get("working_days", "0")).strip()) > 60:
            return "more_than_60_days"
    except ValueError:
        pass
    return "regular"


def row_to_pdf_data(row: Mapping[str, Any]) -> dict[str, Any]:
    data = json_load(str(row.get("form_data") or "{}"))
    data.update(
        {
            "request_type": row.get("request_type", ""),
            "surname": row.get("surname", ""),
            "first_name": row.get("first_name", ""),
            "middle_initial": row.get("middle_initial", ""),
            "first_day_service": display_date(str(row.get("first_day_service") or "")),
            "contact_no": row.get("contact_no", "") or "",
            "tracking_no": row.get("tracking_no", ""),
            "submitted_date": display_date(str(row.get("submitted_at") or "")[:10]),
        }
    )
    for key in ("date_filing", "credits_as_of", "approval_date"):
        data[key] = form_date(str(data.get(key, "")))
    return data


@app.route("/")
def index():
    settings = get_db().execute(
        select(settings_table).where(settings_table.c.id == 1)
    ).mappings().first()
    return render_template("index.html", settings=settings)


@app.route("/health")
def health():
    try:
        get_db().execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except (DatabaseNotConfigured, SQLAlchemyError):
        return {"status": "error", "database": "unavailable"}, 503


@app.route("/request", methods=["GET", "POST"])
def new_request():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        validate_csrf()
        request_type = request.form.get("request_type", "").strip()
        surname = request.form.get("surname", "").strip().upper()
        first_name = request.form.get("first_name", "").strip().upper()

        errors: list[str] = []
        if request_type not in REQUEST_TYPES:
            errors.append("Select a document to request.")
        if not surname:
            errors.append("Surname is required.")
        if not first_name:
            errors.append("First name is required.")

        middle_initial = request.form.get("middle_initial", "").strip().upper().rstrip(".")
        first_day_service = request.form.get("first_day_service", "").strip()
        contact_no = request.form.get("contact_no", "").strip()
        form_data: dict[str, Any] = {}

        if request_type in {"COE", "SERVICE_RECORD"}:
            if not middle_initial:
                errors.append("Middle initial is required.")
            if not first_day_service:
                errors.append("Date of first day of service is required.")
            if not contact_no:
                errors.append("Contact number is required.")
        elif request_type == "FORM_6":
            for key in FORM6_KEYS:
                form_data[key] = request.form.get(key, "").strip()
            required_form6 = {
                "middle_name": "Middle name",
                "date_filing": "Date of filing",
                "position": "Position",
                "salary": "Salary",
                "leave_type": "Type of leave",
                "working_days": "Number of working days",
                "inclusive_dates": "Inclusive dates",
                "commutation": "Commutation",
            }
            for key, label in required_form6.items():
                if not form_data.get(key):
                    errors.append(f"{label} is required for Form 6.")
            if form_data.get("leave_type") == "Others" and not form_data.get("other_leave_type"):
                errors.append("Specify the other type of leave.")
            form_data["form_variant"] = detect_form_variant(form_data)

        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("request_form.html", form=form)

        tracking_no = generate_tracking_no(request_type)
        now = now_iso()
        db = get_db()
        db.execute(
            insert(requests_table).values(
                tracking_no=tracking_no,
                request_type=request_type,
                surname=surname,
                first_name=first_name,
                middle_initial=middle_initial + "." if middle_initial else "",
                first_day_service=first_day_service,
                contact_no=contact_no if request_type in {"COE", "SERVICE_RECORD"} else "",
                form_data=json.dumps(form_data, ensure_ascii=False),
                status="Submitted",
                admin_remarks="",
                submitted_at=now,
                updated_at=now,
            )
        )
        db.commit()
        return redirect(url_for("request_success", tracking_no=tracking_no))

    return render_template("request_form.html", form=form)


@app.route("/request/success/<tracking_no>")
def request_success(tracking_no: str):
    row = get_db().execute(
        select(requests_table).where(
            func.upper(requests_table.c.tracking_no) == tracking_no.upper()
        )
    ).mappings().first()
    if row is None:
        abort(404)
    return render_template("request_success.html", item=row)


@app.route("/track", methods=["GET", "POST"])
def track_request():
    item = None
    searched = False
    tracking_no = request.args.get("tracking", "")
    if request.method == "POST":
        validate_csrf()
        tracking_no = request.form.get("tracking_no", "")
    if tracking_no:
        searched = True
        item = get_db().execute(
            select(requests_table).where(
                func.upper(requests_table.c.tracking_no) == tracking_no.strip().upper()
            )
        ).mappings().first()
        if item is None:
            flash("No request matched that tracking number.", "danger")
    return render_template("track.html", item=item, searched=searched, tracking_no=tracking_no)


@app.route("/request/<tracking_no>/pdf")
@login_required
def request_pdf(tracking_no: str):
    db = get_db()
    row = db.execute(
        select(requests_table).where(
            func.upper(requests_table.c.tracking_no) == tracking_no.upper()
        )
    ).mappings().first()
    if row is None:
        abort(404)
    settings = db.execute(
        select(settings_table).where(settings_table.c.id == 1)
    ).mappings().first()
    data = row_to_pdf_data(row)
    if row["request_type"] == "FORM_6":
        content = build_form6_pdf(data, include_back=True)
        filename = f"{row['tracking_no']}_Form6.pdf"
    else:
        content = build_simple_request_pdf(data, dict(settings or {}))
        suffix = "COE_Request" if row["request_type"] == "COE" else "Service_Record_Request"
        filename = f"{row['tracking_no']}_{suffix}.pdf"
    return send_file(
        io.BytesIO(content),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=filename,
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute(
            select(users_table).where(func.lower(users_table.c.username) == username)
        ).mappings().first()
        if user and password_verify(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            next_url = request.args.get("next", "")
            return redirect(next_url if next_url.startswith("/") else url_for("admin_dashboard"))
        flash("Incorrect username or password.", "danger")
    return render_template("admin_login.html")


@app.route("/admin/logout", methods=["POST"])
@login_required
def admin_logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    status = request.args.get("status", "").strip()
    request_type = request.args.get("type", "").strip()
    query_text = request.args.get("q", "").strip()

    statement = select(requests_table)
    if status in STATUS_OPTIONS:
        statement = statement.where(requests_table.c.status == status)
    if request_type in REQUEST_TYPES:
        statement = statement.where(requests_table.c.request_type == request_type)
    if query_text:
        term = f"%{query_text}%"
        statement = statement.where(
            or_(
                requests_table.c.tracking_no.ilike(term),
                requests_table.c.surname.ilike(term),
                requests_table.c.first_name.ilike(term),
                requests_table.c.contact_no.ilike(term),
            )
        )
    statement = statement.order_by(requests_table.c.submitted_at.desc())
    rows = db.execute(statement).mappings().all()

    summary_rows = db.execute(
        select(
            requests_table.c.status,
            func.count(requests_table.c.id).label("count"),
        ).group_by(requests_table.c.status)
    ).mappings().all()
    summary = {row["status"]: row["count"] for row in summary_rows}

    return render_template(
        "admin_dashboard.html",
        rows=rows,
        summary=summary,
        selected_status=status,
        selected_type=request_type,
        query_text=query_text,
    )


@app.route("/admin/request/<int:request_id>", methods=["GET", "POST"])
@login_required
def admin_request_detail(request_id: int):
    db = get_db()
    row = db.execute(
        select(requests_table).where(requests_table.c.id == request_id)
    ).mappings().first()
    if row is None:
        abort(404)
    form_data = json_load(row["form_data"])

    if request.method == "POST":
        validate_csrf()
        status = request.form.get("status", "Submitted")
        if status not in STATUS_OPTIONS:
            status = "Submitted"
        if row["request_type"] == "FORM_6":
            for key in FORM6_KEYS:
                if key in request.form:
                    form_data[key] = request.form.get(key, "").strip()
        db.execute(
            update(requests_table)
            .where(requests_table.c.id == request_id)
            .values(
                status=status,
                admin_remarks=request.form.get("admin_remarks", "").strip(),
                form_data=json.dumps(form_data, ensure_ascii=False),
                updated_at=now_iso(),
            )
        )
        db.commit()
        flash("Request updated successfully.", "success")
        return redirect(url_for("admin_request_detail", request_id=request_id))

    return render_template("admin_request_detail.html", item=row, data=form_data)


@app.route("/admin/request/<int:request_id>/delete", methods=["POST"])
@login_required
def delete_request(request_id: int):
    validate_csrf()
    db = get_db()
    row = db.execute(
        select(requests_table.c.tracking_no).where(requests_table.c.id == request_id)
    ).mappings().first()
    if row is None:
        abort(404)
    tracking_no = row["tracking_no"]
    db.execute(delete(requests_table).where(requests_table.c.id == request_id))
    db.commit()
    flash(f"Request {tracking_no} was permanently deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    db = get_db()
    if request.method == "POST":
        validate_csrf()
        values = {
            field: request.form.get(field, "").strip()
            for field in [
                "school_name",
                "school_subtitle",
                "division",
                "region",
                "address",
                "records_email",
                "records_contact",
            ]
        }
        db.execute(
            update(settings_table).where(settings_table.c.id == 1).values(**values)
        )
        db.commit()
        flash("System settings updated.", "success")
        return redirect(url_for("admin_settings"))
    settings = db.execute(
        select(settings_table).where(settings_table.c.id == 1)
    ).mappings().first()
    return render_template("admin_settings.html", settings=settings)


@app.route("/admin/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        validate_csrf()
        db = get_db()
        user = db.execute(
            select(users_table).where(users_table.c.id == session["user_id"])
        ).mappings().first()
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not user or not password_verify(user["password_hash"], current):
            flash("Current password is incorrect.", "danger")
        elif len(new) < 10:
            flash("New password must contain at least 10 characters.", "danger")
        elif new != confirm:
            flash("New password confirmation does not match.", "danger")
        else:
            db.execute(
                update(users_table)
                .where(users_table.c.id == user["id"])
                .values(password_hash=password_hash(new))
            )
            db.commit()
            flash("Password changed.", "success")
            return redirect(url_for("admin_dashboard"))
    return render_template("change_password.html")


@app.route("/admin/export.csv")
@login_required
def export_csv():
    rows = get_db().execute(
        select(requests_table).order_by(requests_table.c.submitted_at.desc())
    ).mappings().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Tracking Number",
            "Document",
            "Surname",
            "First Name",
            "Middle Initial",
            "First Day of Service",
            "Contact Number",
            "Status",
            "Submitted",
            "Updated",
            "Remarks",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row["tracking_no"],
                REQUEST_TYPES.get(row["request_type"], row["request_type"]),
                row["surname"],
                row["first_name"],
                row["middle_initial"],
                row["first_day_service"],
                row["contact_no"] or "",
                row["status"],
                row["submitted_at"],
                row["updated_at"],
                row["admin_remarks"],
            ]
        )
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f"attachment; filename=spnhs_requests_{date.today():%Y%m%d}.csv"
    )
    return response


@app.errorhandler(DatabaseNotConfigured)
def database_not_configured(error: DatabaseNotConfigured):
    return render_template("error.html", code=503, message=str(error)), 503


@app.errorhandler(SQLAlchemyError)
def database_error(error: SQLAlchemyError):
    app.logger.exception("Database operation failed")
    return render_template(
        "error.html",
        code=503,
        message="The request database is temporarily unavailable. Please try again shortly.",
    ), 503


@app.errorhandler(400)
def bad_request(error):
    return render_template(
        "error.html",
        code=400,
        message=str(getattr(error, "description", "Bad request")),
    ), 400


@app.errorhandler(404)
def not_found(_error):
    return render_template(
        "error.html",
        code=404,
        message="The requested record or page was not found.",
    ), 404


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
