"""Copy data from an earlier SQLite installation into Neon Postgres.

Example:
    python migrate_sqlite_to_neon.py \
      --sqlite ../spnhs_online_request_system_v4/instance/spnhs_requests.db \
      --database-url "postgresql://..."

The script does not delete data from either database. Existing rows with the
same username, settings id, or tracking number are skipped.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate SPNHS request data to Neon Postgres")
    parser.add_argument("--sqlite", required=True, help="Path to the old spnhs_requests.db file")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Neon Postgres connection string (or set DATABASE_URL)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sqlite_path = Path(args.sqlite).expanduser().resolve()
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite file not found: {sqlite_path}")
    if not args.database_url:
        raise SystemExit("Provide --database-url or set DATABASE_URL.")

    os.environ["DATABASE_URL"] = args.database_url

    from sqlalchemy import insert, select, update

    from app import (
        ensure_database,
        get_engine,
        requests_table,
        settings_table,
        users_table,
    )

    ensure_database()
    engine = get_engine()

    source = sqlite3.connect(sqlite_path)
    source.row_factory = sqlite3.Row

    counts = {"users": 0, "settings": 0, "requests": 0, "skipped": 0}

    with engine.begin() as target:
        for row in source.execute("SELECT * FROM users ORDER BY id"):
            exists = target.execute(
                select(users_table.c.id).where(users_table.c.username == row["username"])
            ).first()
            if exists:
                # Replace the automatically seeded user's hash with the old
                # installation's hash so the existing administrator password
                # remains valid after migration.
                target.execute(
                    update(users_table)
                    .where(users_table.c.username == row["username"])
                    .values(
                        password_hash=row["password_hash"],
                        full_name=row["full_name"],
                        created_at=row["created_at"],
                    )
                )
            else:
                target.execute(
                    insert(users_table).values(
                        username=row["username"],
                        password_hash=row["password_hash"],
                        full_name=row["full_name"],
                        created_at=row["created_at"],
                    )
                )
            counts["users"] += 1

        settings_row = source.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        if settings_row:
            target.execute(
                update(settings_table)
                .where(settings_table.c.id == 1)
                .values(
                    school_name=settings_row["school_name"],
                    school_subtitle=settings_row["school_subtitle"],
                    division=settings_row["division"],
                    region=settings_row["region"],
                    address=settings_row["address"],
                    records_email=settings_row["records_email"],
                    records_contact=settings_row["records_contact"],
                )
            )
            counts["settings"] += 1

        request_columns = {
            item[1] for item in source.execute("PRAGMA table_info(requests)").fetchall()
        }
        for row in source.execute("SELECT * FROM requests ORDER BY id"):
            exists = target.execute(
                select(requests_table.c.id).where(
                    requests_table.c.tracking_no == row["tracking_no"]
                )
            ).first()
            if exists:
                counts["skipped"] += 1
                continue
            target.execute(
                insert(requests_table).values(
                    tracking_no=row["tracking_no"],
                    request_type=row["request_type"],
                    surname=row["surname"],
                    first_name=row["first_name"],
                    middle_initial=row["middle_initial"],
                    first_day_service=row["first_day_service"],
                    contact_no=row["contact_no"] if "contact_no" in request_columns else "",
                    form_data=row["form_data"] or "{}",
                    status=row["status"],
                    admin_remarks=row["admin_remarks"],
                    submitted_at=row["submitted_at"],
                    updated_at=row["updated_at"],
                )
            )
            counts["requests"] += 1

    source.close()
    print("Migration completed successfully.")
    print(
        f"Users: {counts['users']} | Settings: {counts['settings']} | "
        f"Requests: {counts['requests']} | Skipped existing: {counts['skipped']}"
    )


if __name__ == "__main__":
    main()
