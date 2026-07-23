# SPNHS-SHS Online Records Request System v5

A Vercel-ready online filing system for **Sangley Point National High School – Senior High School**.

It accepts and tracks requests for:

1. Civil Service Form No. 6, Revised 2020 – Application for Leave
2. Certificate of Employment
3. Service Record

The school logo and logo-based colors are included. Printable PDFs are available only after an administrator signs in.

## Version 5 changes

- Converted the persistent database layer to **Neon PostgreSQL** for Vercel hosting.
- Kept a local SQLite fallback for testing on a computer.
- Added serverless-safe database connections.
- PDF files are generated in memory and are not stored on Vercel's temporary filesystem.
- Moved website assets to `public/`, which Vercel serves through its CDN.
- Added Vercel configuration and a Python version file.
- Added a `/health` endpoint for checking the database connection.
- Added an optional migration tool for copying an existing v4 SQLite database into Neon.

## Features retained

- Online Form 6, COE, and Service Record filing
- Contact number for COE and Service Record
- Unique tracking number
- Public status tracking
- Records Office dashboard
- Status and remarks updates
- Admin-only PDF generation
- Form 6 Section 7 completion
- Delete request function
- CSV export
- Password change
- School settings

## Fast deployment overview

Read `VERCEL_DEPLOYMENT_GUIDE.md` for the complete instructions.

The required production environment variables are:

```text
DATABASE_URL=<Neon pooled Postgres connection string>
SECRET_KEY=<long random secret>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong initial password>
ADMIN_FULL_NAME=SPNHS-SHS Records Administrator
```

Vercel automatically detects the Flask application from the root `app.py` file. No custom Build Command or Output Directory is required.

## Local Windows testing

1. Extract the ZIP.
2. Double-click `setup_windows.bat`.
3. Double-click `run_windows.bat`.
4. Open `http://127.0.0.1:5000`.

When `DATABASE_URL` is not set and the app is not running on Vercel, it uses:

```text
instance/spnhs_requests.db
```

### Default local administrator

```text
Username: admin
Password: SPNHS2026!
```

Change the password immediately after signing in.

## Important folders and files

- `app.py` – Flask routes, PostgreSQL/SQLite access, login, tracking, and admin functions
- `pdf_builder.py` – Form 6 and request PDF generation
- `templates/` – web page layouts
- `public/css/style.css` – colors and interface design
- `public/img/spnhs_logo.png` – school logo
- `form_templates/` – uploaded Form 6 PDF references
- `vercel.json` – Vercel Function configuration
- `.python-version` – Python runtime selection
- `migrate_sqlite_to_neon.py` – optional old-data migration utility

## Database initialization

The app automatically creates its PostgreSQL tables on the first request. It also creates the initial administrator using `ADMIN_USERNAME` and `ADMIN_PASSWORD` only when that username does not already exist.

Changing `ADMIN_PASSWORD` in Vercel after the administrator has already been created will not change the saved password. Use **Admin → Password** inside the system.

## Migrating an existing v4 database

The Vercel website can start with an empty Neon database. To copy old v4 requests, run the migration script from your computer after installing the requirements:

```bash
python migrate_sqlite_to_neon.py \
  --sqlite "path/to/v4/instance/spnhs_requests.db" \
  --database-url "YOUR_NEON_CONNECTION_STRING"
```

The migration skips existing tracking numbers and does not delete the original SQLite database.

## Security and privacy

Before collecting actual personnel data:

- use a strong `SECRET_KEY` and administrator password
- keep `DATABASE_URL` private
- change the initial admin password
- limit admin access to authorized Records Office personnel
- create a privacy notice and retention policy
- establish regular database exports or backups
- review the deployment under the Philippine Data Privacy Act and applicable DepEd rules

## Form verification

The PDF generator uses the uploaded Form 6 files as backgrounds. Print sample applications before official rollout and have the Records Office verify the field placement, leave variants, and signatory workflow.
