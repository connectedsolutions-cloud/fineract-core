#!/usr/bin/env python3
"""Keep protected sandbox configuration across a whole-tenant baseline restore.

The snapshot is deliberately local and private: it contains password hashes,
reset tokens, and office signing settings. Never print its contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import psycopg


TABLES = (
    "m_office",
    "m_staff",
    "m_staff_office",
    "credesal_staff_profile",
    "m_permission",
    "m_role",
    "m_appuser",
    "m_password_validation_policy",
    "m_appuser_office",
    "m_appuser_role",
    "m_role_permission",
    "m_appuser_previous_password",
    "m_appuser_password_reset_token",
    "twofactor_access_token",
    "m_appuser_saved_report",
)
REPLACED = (
    "m_staff_office",
    "credesal_staff_profile",
    "m_appuser_office",
    "m_appuser_role",
    "m_role_permission",
    "m_appuser_previous_password",
    "m_appuser_password_reset_token",
    "twofactor_access_token",
)
SEQUENCED = (
    "m_office",
    "m_staff",
    "m_permission",
    "m_role",
    "m_appuser",
    "m_appuser_previous_password",
    "m_appuser_password_reset_token",
    "twofactor_access_token",
)

# Only reviewed operational mappings survive a disposable-tenant reset. Activity
# 103 has no approved account, and opening-balance activity 300 is out of scope.
FINANCIAL_ACTIVITY_ACCOUNTS = {
    100: ("1510", 1),
    101: ("111001030200", 1),
    102: ("1110010199", 1),
    200: ("2130050101", 2),
    201: ("222099910101", 2),
    202: ("222099910201", 2),
}


def capture_financial_activity_mappings(cur: psycopg.Cursor) -> list[dict[str, object]]:
    cur.execute(
        """SELECT f.financial_activity_type, a.gl_code, a.classification_enum,
                  a.account_usage, a.disabled
             FROM acc_gl_financial_activity_account f
             JOIN acc_gl_account a ON a.id = f.gl_account_id
            WHERE f.financial_activity_type = ANY(%s)
            ORDER BY f.financial_activity_type""",
        (list(FINANCIAL_ACTIVITY_ACCOUNTS),),
    )
    saved = []
    for activity_id, gl_code, classification, usage, disabled in cur.fetchall():
        expected_code, expected_classification = FINANCIAL_ACTIVITY_ACCOUNTS[activity_id]
        if (gl_code != expected_code or classification != expected_classification
                or usage != 1 or disabled):
            raise RuntimeError(f"Financial activity {activity_id} differs from the reviewed mapping")
        saved.append({"financial_activity_id": activity_id, "gl_code": gl_code})
    return saved


def restore_financial_activity_mappings(cur: psycopg.Cursor, saved: object) -> None:
    if not isinstance(saved, list):
        raise RuntimeError("Financial activity snapshot is invalid")
    seen = set()
    for item in saved:
        if not isinstance(item, dict) or set(item) != {"financial_activity_id", "gl_code"}:
            raise RuntimeError("Financial activity snapshot entry is invalid")
        activity_id, gl_code = item["financial_activity_id"], item["gl_code"]
        if (type(activity_id) is not int or activity_id in seen
                or activity_id not in FINANCIAL_ACTIVITY_ACCOUNTS
                or gl_code != FINANCIAL_ACTIVITY_ACCOUNTS[activity_id][0]):
            raise RuntimeError("Financial activity snapshot differs from the reviewed mapping")
        seen.add(activity_id)
        expected_classification = FINANCIAL_ACTIVITY_ACCOUNTS[activity_id][1]
        cur.execute(
            """SELECT id, classification_enum, account_usage, disabled
                 FROM acc_gl_account WHERE gl_code = %s""",
            (gl_code,),
        )
        accounts = cur.fetchall()
        if (len(accounts) != 1 or accounts[0][1] != expected_classification
                or accounts[0][2] != 1 or accounts[0][3]):
            raise RuntimeError(f"Financial activity {activity_id} target GL account is invalid")
        account_id = accounts[0][0]
        cur.execute(
            "SELECT gl_account_id FROM acc_gl_financial_activity_account "
            "WHERE financial_activity_type = %s",
            (activity_id,),
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO acc_gl_financial_activity_account "
                "(financial_activity_type, gl_account_id) VALUES (%s, %s)",
                (activity_id, account_id),
            )
        elif existing[0] != account_id:
            raise RuntimeError(f"Financial activity {activity_id} conflicts with the restored baseline")
        cur.execute(
            "SELECT gl_account_id FROM acc_gl_financial_activity_account "
            "WHERE financial_activity_type = %s",
            (activity_id,),
        )
        if cur.fetchone() != (account_id,):
            raise RuntimeError(f"Financial activity {activity_id} was not restored")


def columns(cur: psycopg.Cursor, table: str) -> list[str]:
    cur.execute(
        """SELECT attname FROM pg_attribute
           WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped
           ORDER BY attnum""",
        (f"public.{table}",),
    )
    return [row[0] for row in cur.fetchall()]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def capture(database: str, directory: Path) -> None:
    directory.mkdir(mode=0o700)
    try:
        with psycopg.connect(dbname=database, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SELECT count(*) FROM m_staff WHERE image_id IS NOT NULL")
                if cur.fetchone()[0]:
                    raise RuntimeError(
                        "An employee has an image link; the clean baseline cannot "
                        "preserve it without also preserving the referenced image"
                    )
                cur.execute("SELECT count(*) FROM m_selfservice_user_client_mapping")
                if cur.fetchone()[0]:
                    raise RuntimeError(
                        "Self-service users are linked to clients; the clean baseline "
                        "cannot preserve those access links without client data"
                    )
                manifest: dict = {"database": database, "tables": {}, "saved_reports": []}
                for table in TABLES:
                    names = columns(cur, table)
                    path = directory / f"{table}.copy"
                    with path.open("wb") as handle:
                        os.chmod(path, 0o600)
                        with cur.copy(f"COPY public.{table} TO STDOUT (FORMAT binary)") as stream:
                            for block in stream:
                                handle.write(block)
                    cur.execute(f"SELECT count(*) FROM public.{table}")
                    manifest["tables"][table] = {
                        "columns": names,
                        "count": cur.fetchone()[0],
                        "sha256": digest(path),
                    }
                cur.execute(
                    """SELECT s.appuser_id, r.report_name
                       FROM m_appuser_saved_report s
                       JOIN stretchy_report r ON r.id = s.report_id
                       ORDER BY s.appuser_id, r.report_name"""
                )
                manifest["saved_reports"] = cur.fetchall()
                if len(manifest["saved_reports"]) != manifest["tables"]["m_appuser_saved_report"]["count"]:
                    raise RuntimeError("A saved report has no report definition")
                manifest["financial_activity_mappings"] = capture_financial_activity_mappings(cur)
                cur.execute("COMMIT")
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        os.chmod(manifest_path, 0o600)
    except BaseException:
        shutil.rmtree(directory)
        raise


def upsert(cur: psycopg.Cursor, table: str, names: list[str], key: str, order: str = "") -> None:
    selected = ", ".join(f'"{name}"' for name in names)
    updates = ", ".join(
        f'"{name}" = EXCLUDED."{name}"'
        for name in names if name != key and not (key == "code" and name == "id")
    )
    selection_end = order or "WHERE true"
    cur.execute(
        f"INSERT INTO public.{table} ({selected}) "
        f"SELECT {selected} FROM pg_temp.stage_{table} {selection_end} "
        f"ON CONFLICT (\"{key}\") DO UPDATE SET {updates}"
    )


def upsert_staff(cur: psycopg.Cursor, names: list[str]) -> None:
    selected = ", ".join(f'"{name}"' for name in names)
    source = ", ".join(
        'NULL AS "organisational_role_parent_staff_id"'
        if name == "organisational_role_parent_staff_id" else f'"{name}"'
        for name in names
    )
    updates = ", ".join(
        f'"{name}" = EXCLUDED."{name}"'
        for name in names if name not in ("id", "organisational_role_parent_staff_id")
    )
    cur.execute(
        f"INSERT INTO m_staff ({selected}) "
        f"SELECT {source} FROM pg_temp.stage_m_staff WHERE true "
        f"ON CONFLICT (id) DO UPDATE SET {updates}"
    )
    cur.execute(
        """UPDATE m_staff staff
           SET organisational_role_parent_staff_id = saved.organisational_role_parent_staff_id
           FROM pg_temp.stage_m_staff saved WHERE staff.id = saved.id"""
    )


def restore(database: str, directory: Path) -> None:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["database"] != database or set(manifest["tables"]) != set(TABLES):
        raise RuntimeError("Access snapshot does not match this database or table set")
    for table in TABLES:
        if digest(directory / f"{table}.copy") != manifest["tables"][table]["sha256"]:
            raise RuntimeError(f"Access snapshot checksum mismatch: {table}")

    with psycopg.connect(dbname=database) as conn:
        with conn.cursor() as cur:
            for table in TABLES:
                names = columns(cur, table)
                if names != manifest["tables"][table]["columns"]:
                    raise RuntimeError(f"Protected table schema changed: {table}")
                cur.execute(f"CREATE TEMP TABLE stage_{table} AS SELECT * FROM public.{table} WITH NO DATA")
                with cur.copy(f"COPY pg_temp.stage_{table} FROM STDIN (FORMAT binary)") as stream:
                    with (directory / f"{table}.copy").open("rb") as handle:
                        for block in iter(lambda: handle.read(1024 * 1024), b""):
                            stream.write(block)
                cur.execute(f"SELECT count(*) FROM pg_temp.stage_{table}")
                if cur.fetchone()[0] != manifest["tables"][table]["count"]:
                    raise RuntimeError(f"Protected row count changed: {table}")

            # The baseline predates some permission definitions and the saved-report
            # table. Liquibase must finish before this transaction can run.
            upsert(cur, "m_office", columns(cur, "m_office"), "id", "ORDER BY hierarchy")
            upsert_staff(cur, columns(cur, "m_staff"))
            upsert(cur, "m_permission", columns(cur, "m_permission"), "code")
            upsert(cur, "m_role", columns(cur, "m_role"), "id")
            upsert(cur, "m_appuser", columns(cur, "m_appuser"), "id")
            upsert(cur, "m_password_validation_policy", columns(cur, "m_password_validation_policy"), "id")

            for table in ("m_office", "m_staff", "m_role", "m_appuser", "m_password_validation_policy"):
                cur.execute(
                    f"SELECT count(*) FROM pg_temp.stage_{table} saved "
                    f"WHERE NOT EXISTS (SELECT 1 FROM public.{table} current "
                    "WHERE to_jsonb(current) = to_jsonb(saved))"
                )
                if cur.fetchone()[0]:
                    raise RuntimeError(f"Protected values were not restored: {table}")
            cur.execute(
                """SELECT count(*) FROM pg_temp.stage_m_permission saved
                   LEFT JOIN m_permission current ON current.code = saved.code
                   WHERE current.id IS NULL
                      OR to_jsonb(current) - 'id' IS DISTINCT FROM to_jsonb(saved) - 'id'"""
            )
            if cur.fetchone()[0]:
                raise RuntimeError("Protected permission definitions were not restored")
            cur.execute(
                "SELECT count(*) FROM m_appuser WHERE id NOT IN (SELECT id FROM pg_temp.stage_m_appuser)"
            )
            if cur.fetchone()[0]:
                raise RuntimeError("Baseline would resurrect a removed user; access restore refused")
            cur.execute(
                "SELECT count(*) FROM m_staff WHERE id NOT IN (SELECT id FROM pg_temp.stage_m_staff)"
            )
            if cur.fetchone()[0]:
                raise RuntimeError("Baseline would resurrect a removed employee; access restore refused")

            for table in REPLACED:
                cur.execute(f"DELETE FROM public.{table}")
            for table in REPLACED:
                names = columns(cur, table)
                selected = ", ".join(f'"{name}"' for name in names)
                if table == "m_role_permission":
                    cur.execute(
                        """INSERT INTO m_role_permission (role_id, permission_id)
                           SELECT rp.role_id, target.id
                           FROM pg_temp.stage_m_role_permission rp
                           JOIN pg_temp.stage_m_permission old ON old.id = rp.permission_id
                           JOIN m_permission target ON target.code = old.code"""
                    )
                else:
                    cur.execute(
                        f"INSERT INTO public.{table} ({selected}) "
                        f"SELECT {selected} FROM pg_temp.stage_{table}"
                    )
                cur.execute(f"SELECT count(*) FROM public.{table}")
                if cur.fetchone()[0] != manifest["tables"][table]["count"]:
                    raise RuntimeError(f"Protected row count not restored: {table}")

            cur.execute("DELETE FROM m_appuser_saved_report")
            for user_id, report_name in manifest["saved_reports"]:
                cur.execute(
                    """INSERT INTO m_appuser_saved_report (appuser_id, report_id)
                       SELECT %s, id FROM stretchy_report WHERE report_name = %s""",
                    (user_id, report_name),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"Saved report definition is missing: {report_name}")
            cur.execute("SELECT count(*) FROM m_appuser_saved_report")
            if cur.fetchone()[0] != len(manifest["saved_reports"]):
                raise RuntimeError("Saved report list was not fully restored")

            # Older pending access snapshots did not capture financial mappings.
            restore_financial_activity_mappings(cur, manifest.get("financial_activity_mappings", []))

            for table in SEQUENCED:
                cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"public.{table}",))
                sequence = cur.fetchone()[0]
                if sequence:
                    cur.execute(
                        f"SELECT setval(%s, GREATEST((SELECT COALESCE(max(id), 0) FROM public.{table}), 1), true)",
                        (sequence,),
                    )
            # Commit only after every protected relationship and count is valid.
    shutil.rmtree(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "restore"))
    parser.add_argument("database")
    parser.add_argument("snapshot_dir", type=Path)
    args = parser.parse_args()
    if args.action == "capture":
        capture(args.database, args.snapshot_dir)
        print("Protected access and reviewed financial activity mappings captured")
    else:
        restore(args.database, args.snapshot_dir)
        print("Protected access and reviewed financial activity mappings restored")


if __name__ == "__main__":
    main()
