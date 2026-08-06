"""
Lightweight schema migrations
==============================
This project has no Alembic set up -- `db.create_all()` only creates
tables that don't exist yet, it never alters an existing table. So
whenever a new column is added to an existing model, an already-
deployed SQLite file needs it patched in by hand. This module does
that additively (ALTER TABLE ... ADD COLUMN) at startup, after
db.create_all() has had a chance to create any brand-new tables.

Safe to run every time: it only adds columns that are missing.
"""

from sqlalchemy import inspect, text

_ADDITIVE_COLUMNS = {
    "transactions": [
        ("source", "VARCHAR(20)", "'upload'"),
        ("entered_by", "INTEGER", None),
        ("created_at", "DATETIME", None),
    ],
    "user_profiles": [
        ("id_number", "VARCHAR(20)", None),
        ("bank_account_holder", "VARCHAR(120)", None),
        ("bank_name", "VARCHAR(80)", None),
        ("bank_account_number", "VARCHAR(34)", None),
        ("bank_branch_code", "VARCHAR(10)", None),
    ],
    "group_members": [
        ("occupation", "VARCHAR(120)", None),
        ("next_of_kin_name", "VARCHAR(120)", None),
        ("next_of_kin_phone", "VARCHAR(32)", None),
        ("custom_fields_json", "TEXT", None),
    ],
    "group_settings": [
        ("last_retrained_at", "DATETIME", None),
    ],
}


def run_light_migrations(db) -> None:
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    with db.engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for name, sqltype, default in columns:
                if name in existing_cols:
                    continue
                ddl = f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"
                if default is not None:
                    ddl += f" DEFAULT {default}"
                conn.execute(text(ddl))
