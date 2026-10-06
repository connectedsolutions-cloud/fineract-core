#!/usr/bin/env python3
"""Copy local Fineract sandbox into the existing production default database.

Usage (from fineract-core):
  tools/arissto-sync/.venv/bin/python scripts/copy-sandbox-to-prod.py inspect
  tools/arissto-sync/.venv/bin/python scripts/copy-sandbox-to-prod.py stage --directory /private/path/run-YYYYMMDD
  tools/arissto-sync/.venv/bin/python scripts/copy-sandbox-to-prod.py promote --directory /private/path/run-YYYYMMDD --confirm promote:STAGE_DB:fineract_default

Both Fineract applications must be stopped for stage and promote. Production
users are authoritative; sandbox-only users are included. Stage uses an
unregistered database for validation; promotion restores into the existing
fineract_default database in one transaction. A full private production pg_dump
is retained for rollback.
For the configured DigitalOcean default-pool URL, the script derives the direct
port 25060 and database fineract_default from the same credentials. Other
pooler configurations require FINERACT_PROD_DIRECT_PG_URL explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "arissto-sync"))
from arissto_sync.config import load_env  # noqa: E402

BUSINESS = ("m_client", "m_loan", "m_savings_account", "m_share_account", "acc_gl_journal_entry")
EMPTY_PROD_AUTH = ("m_appuser_previous_password", "m_appuser_password_reset_token",
                   "twofactor_access_token", "m_selfservice_user_client_mapping")
LINKS = ("m_appuser_role", "m_appuser_office")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def profiles():
    load_env(ROOT / "tools" / "arissto-sync" / ".env")
    local = conninfo_to_dict(os.environ["FINERACT_LOCAL_PG_URL"])
    prod_read = conninfo_to_dict(os.environ["FINERACT_PROD_PG_URL"])
    direct_url = os.environ.get("FINERACT_PROD_DIRECT_PG_URL")
    prod_direct = conninfo_to_dict(direct_url) if direct_url else None
    if (prod_direct is None and
            prod_read.get("host", "").endswith(".db.ondigitalocean.com") and
            prod_read.get("port") == "25061" and
            prod_read.get("dbname") == "default-pool"):
        prod_direct = prod_read | {"port": "25060", "dbname": "fineract_default"}
    require(local.get("dbname") == "fineract_sandbox", "Source must be fineract_sandbox")
    require(local.get("host") in {"localhost", "127.0.0.1", "::1"}, "Source must be local")
    require(prod_read.get("host") not in {"localhost", "127.0.0.1", "::1", None},
            "Target must be remote")
    if prod_direct:
        require(prod_direct.get("dbname") == "fineract_default",
                "Direct target must be fineract_default")
        require(prod_direct.get("host") == prod_read.get("host"),
                "Direct target host differs from configured production host")
        require((prod_direct.get("host"), prod_direct.get("port")) !=
                (prod_read.get("host"), prod_read.get("port")) or
                prod_read.get("dbname") == "fineract_default",
                "Direct target still points at the production pooler")
    return local, prod_read, prod_direct


def connect(profile, dbname=None, **options):
    params = profile | ({"dbname": dbname} if dbname else {})
    return psycopg.connect(make_conninfo("", **params), connect_timeout=15, **options)


def maintenance_db():
    return os.environ.get("FINERACT_PROD_MAINT_DB", "defaultdb")


def pg_environment(profile):
    env = os.environ.copy()
    for key, name in {"host": "PGHOST", "port": "PGPORT", "user": "PGUSER",
                      "password": "PGPASSWORD", "sslmode": "PGSSLMODE",
                      "sslrootcert": "PGSSLROOTCERT"}.items():
        if key in profile:
            env[name] = str(profile[key])
    return env


def pg(program, profile, *args):
    subprocess.run([program, *args], env=pg_environment(profile), check=True)


def columns(cur, table):
    return [row["column_name"] for row in cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,)).fetchall()]


def all_rows(cur, table):
    return cur.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table))).fetchall()


def count(cur, table):
    return cur.execute(sql.SQL("SELECT count(*) AS n FROM public.{}").format(
        sql.Identifier(table))).fetchone()["n"]


def snapshot(profile):
    with connect(profile, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            user_rows = all_rows(cur, "m_appuser")
            user_rows.sort(key=lambda row: row["username"])
            users_hash = hashlib.sha256(json.dumps(user_rows, default=str, sort_keys=True).encode()).hexdigest()
            return {"database": cur.execute("SELECT current_database() AS db").fetchone()["db"],
                    "business": {table: count(cur, table) for table in BUSINESS},
                    "users": len(user_rows),
                    "user_hash": users_hash,
                    "changesets": count(cur, "databasechangelog")}


def identity_map(cur, table, label):
    return {row["id"]: row[label] for row in cur.execute(
        sql.SQL("SELECT id, {} FROM public.{}").format(
            sql.Identifier(label), sql.Identifier(table))).fetchall()}


def inspect_users(local, prod):
    with connect(local, row_factory=dict_row) as lc, connect(prod, row_factory=dict_row) as pc:
        lc.execute("SET TRANSACTION READ ONLY")
        pc.execute("SET TRANSACTION READ ONLY")
        with lc.cursor() as l, pc.cursor() as p:
            require(columns(l, "m_appuser") == columns(p, "m_appuser"),
                    "m_appuser schemas differ")
            local_users = {u["username"]: u for u in all_rows(l, "m_appuser")}
            prod_users = {u["username"]: u for u in all_rows(p, "m_appuser")}
            require(len(local_users) == count(l, "m_appuser") and
                    len(prod_users) == count(p, "m_appuser"), "Duplicate username")
            shared = local_users.keys() & prod_users.keys()
            require(all(local_users[name]["id"] == prod_users[name]["id"] for name in shared),
                    "A shared username has different IDs")
            local_ids = {u["id"] for u in local_users.values()}
            prod_only = prod_users.keys() - local_users.keys()
            require(all(prod_users[name]["id"] not in local_ids for name in prod_only),
                    "A production-only user ID collides with a sandbox user")
            for table, label in (("m_role", "name"), ("m_office", "name"),
                                 ("m_staff", "display_name")):
                lm, pm = identity_map(l, table, label), identity_map(p, table, label)
                require(all(lm.get(key) == value for key, value in pm.items() if key in lm),
                        f"{table} identity collision")
            for table in EMPTY_PROD_AUTH:
                require(count(p, table) == 0,
                        f"Production {table} contains records needing a separate merge")
            # Production has no saved-report table at present. If added later, do
            # not silently replace a user's saved report preferences.
            if p.execute("SELECT to_regclass('public.m_appuser_saved_report') AS t").fetchone()["t"]:
                require(count(p, "m_appuser_saved_report") == 0,
                        "Production saved reports need a separate merge")
            return {"shared": len(shared), "sandbox_only": len(local_users.keys() - prod_users.keys()),
                    "production_only": len(prod_only)}


def no_sessions(profile, dbname):
    with connect(profile, maintenance_db() if profile["dbname"] == "fineract_default" else profile["dbname"],
                 autocommit=True) as conn:
        count_other = conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
            (dbname,)).fetchone()[0]
    require(count_other == 0, f"{dbname} has {count_other} database sessions; stop Fineract and other clients")


def insert(cur, table, row):
    names = list(row)
    cur.execute(sql.SQL("INSERT INTO public.{} ({}) VALUES ({})").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, names)),
        sql.SQL(",").join(sql.Placeholder() for _ in names)), [row[name] for name in names])


def merge_production_users(prod, stage):
    with connect(prod, row_factory=dict_row) as pc, connect(prod, stage, row_factory=dict_row) as sc:
        pc.execute("SET TRANSACTION READ ONLY")
        with pc.cursor() as p, sc.cursor() as s:
            require(columns(p, "m_appuser") == columns(s, "m_appuser"), "Staged user schema differs")
            production = all_rows(p, "m_appuser")
            staged = {u["username"]: u for u in all_rows(s, "m_appuser")}
            staged_ids = {u["id"] for u in staged.values()}
            office_ids = set(identity_map(s, "m_office", "name"))
            staff_ids = set(identity_map(s, "m_staff", "display_name"))
            role_ids = set(identity_map(s, "m_role", "name"))
            for table, label in (("m_role", "name"), ("m_office", "name"),
                                 ("m_staff", "display_name")):
                sm, pm = identity_map(s, table, label), identity_map(p, table, label)
                require(all(sm.get(key) == value for key, value in pm.items() if key in sm),
                        f"{table} identity changed")
            for user in production:
                require(user["office_id"] in office_ids, "Production user office absent from sandbox")
                require(user["staff_id"] is None or user["staff_id"] in staff_ids,
                        "Production user staff absent from sandbox")
                match = staged.get(user["username"])
                if match:
                    require(match["id"] == user["id"], "Shared username ID changed")
                    names = [name for name in user if name not in {"id", "username"}]
                    s.execute(sql.SQL("UPDATE m_appuser SET {} WHERE id=%s").format(
                        sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(name))
                                          for name in names)),
                        [user[name] for name in names] + [user["id"]])
                else:
                    require(user["id"] not in staged_ids, "Production-only user ID collision")
                    insert(s, "m_appuser", user)
            prod_ids = [user["id"] for user in production]
            for table, key, allowed in (("m_appuser_role", "role_id", role_ids),
                                         ("m_appuser_office", "office_id", office_ids)):
                linked = all_rows(p, table)
                require(all(row[key] in allowed for row in linked),
                        f"Production {table} references a missing role or office")
                s.execute(sql.SQL("DELETE FROM public.{} WHERE appuser_id = ANY(%s)").format(
                    sql.Identifier(table)), (prod_ids,))
                for row in linked:
                    insert(s, table, row)
                actual_links = s.execute(sql.SQL(
                    "SELECT appuser_id, {} FROM public.{} WHERE appuser_id = ANY(%s)").format(
                        sql.Identifier(key), sql.Identifier(table)), (prod_ids,)).fetchall()
                require({(row["appuser_id"], row[key]) for row in actual_links} ==
                        {(row["appuser_id"], row[key]) for row in linked},
                        f"Production {table} links were not preserved")
            sequence = s.execute("SELECT pg_get_serial_sequence('public.m_appuser','id') AS seq").fetchone()["seq"]
            if sequence:
                s.execute("SELECT setval(%s, GREATEST((SELECT COALESCE(max(id),0) FROM m_appuser),1), true)",
                          (sequence,))
            for user in production:
                actual = s.execute("SELECT * FROM m_appuser WHERE id=%s", (user["id"],)).fetchone()
                require(actual == user, "Production user was not preserved exactly")
            return count(s, "m_appuser")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(local, prod, directory):
    require(not directory.exists(), "Output directory already exists")
    no_sessions(local, "fineract_sandbox")
    no_sessions(prod, "fineract_default")
    before_local, before_prod = snapshot(local), snapshot(prod)
    require(not any(before_prod["business"].values()),
            "Production has business data; this script only supports the current empty-business target")
    users = inspect_users(local, prod)
    stage_db = "fineract_default_stage_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    directory.mkdir(parents=True, mode=0o700)
    source_dump = directory / "sandbox.dump"
    backup_dump = directory / "production-before.dump"
    pg("pg_dump", local, "--format=custom", "--no-owner", "--no-privileges",
       "--file", str(source_dump), "fineract_sandbox")
    pg("pg_dump", prod, "--format=custom", "--no-owner", "--no-privileges",
       "--file", str(backup_dump), "fineract_default")
    source_dump.chmod(0o600)
    backup_dump.chmod(0o600)
    require(snapshot(local) == before_local and snapshot(prod) == before_prod,
            "A tenant changed while being dumped")
    with connect(prod, maintenance_db(), autocommit=True) as admin:
        require(admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (stage_db,)).fetchone() is None,
                "Staging database name already exists")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(stage_db)))
    pg("pg_restore", prod, "--exit-on-error", "--no-owner", "--no-privileges",
       "--dbname", stage_db, str(source_dump))
    staged_profile = prod | {"dbname": stage_db}
    restored = snapshot(staged_profile)
    require(restored["business"] == before_local["business"] and
            restored["changesets"] == before_local["changesets"], "Staged restore differs from source")
    final_users = merge_production_users(prod, stage_db)
    require(final_users == before_local["users"] + users["production_only"],
            "Staged user count differs")
    after = snapshot(staged_profile)
    require(after["business"] == before_local["business"], "Business data changed during user merge")
    candidate_dump = directory / "candidate.dump"
    pg("pg_dump", staged_profile, "--format=custom", "--no-owner", "--no-privileges",
       "--file", str(candidate_dump), stage_db)
    candidate_dump.chmod(0o600)
    require(snapshot(staged_profile) == after, "Staged database changed during candidate dump")
    manifest = {"staging_database": stage_db, "source": before_local, "production": before_prod,
                "staged": after, "user_sets": users,
                "source_dump_sha256": sha256(source_dump),
                "production_backup_sha256": sha256(backup_dump),
                "candidate_dump_sha256": sha256(candidate_dump)}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (directory / "manifest.json").chmod(0o600)
    print(json.dumps({"staging_database": stage_db, "manifest": str(directory / "manifest.json"),
                      "user_sets": users, "business_counts": after["business"]}, indent=2))


def promote(local, prod, directory, confirmation):
    manifest = json.loads((directory / "manifest.json").read_text())
    stage_db = manifest["staging_database"]
    require(stage_db.startswith("fineract_default_stage_"), "Invalid staging database")
    expected = f"promote:{stage_db}:fineract_default"
    require(confirmation == expected, f"Use --confirm {expected}")
    require(sha256(directory / "sandbox.dump") == manifest["source_dump_sha256"],
            "Sandbox dump checksum changed")
    require(sha256(directory / "production-before.dump") == manifest["production_backup_sha256"],
            "Production backup checksum changed")
    require(sha256(directory / "candidate.dump") == manifest["candidate_dump_sha256"],
            "Candidate dump checksum changed")
    no_sessions(prod, "fineract_default")
    no_sessions(prod, stage_db)
    no_sessions(local, "fineract_sandbox")
    require(snapshot(local) == manifest["source"], "Local sandbox changed after staging")
    require(snapshot(prod) == manifest["production"], "Production changed after staging")
    require(snapshot(prod | {"dbname": stage_db}) == manifest["staged"],
            "Staging changed after validation")
    # --single-transaction rolls back the entire restore on SQL failure. This
    # keeps the existing database and tenant registration in place throughout.
    pg("pg_restore", prod, "--single-transaction", "--exit-on-error", "--clean",
       "--if-exists", "--no-owner", "--no-privileges", "--dbname",
       "fineract_default", str(directory / "candidate.dump"))
    require(snapshot(prod) == manifest["staged"],
            "Promotion finished but verification differed; keep Fineract stopped")
    print(json.dumps({"promoted_into_existing_database": "fineract_default",
                      "backup": str(directory / "production-before.dump")}, indent=2))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("inspect", "stage", "promote"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--confirm")
    args = parser.parse_args()
    local, prod_read, prod_direct = profiles()
    if args.action == "inspect":
        a, b = snapshot(local), snapshot(prod_read)
        require(b["database"] == "fineract_default", "Production URL resolved to another database")
        if prod_direct:
            direct = snapshot(prod_direct)
            require(direct == b, "Derived direct endpoint differs from production pooler")
        print(json.dumps({"local": {k: v for k, v in a.items() if k != "user_hash"},
                          "production": {k: v for k, v in b.items() if k != "user_hash"},
                          "user_sets": inspect_users(local, prod_read)}, indent=2))
    elif args.action == "stage":
        require(args.directory is not None, "stage requires --directory")
        require(prod_direct is not None, "Set FINERACT_PROD_DIRECT_PG_URL to the direct endpoint")
        require(snapshot(prod_direct)["database"] == "fineract_default",
                "Direct target resolved to another database")
        stage(local, prod_direct, args.directory)
    else:
        require(args.directory is not None, "promote requires --directory")
        require(prod_direct is not None, "Set FINERACT_PROD_DIRECT_PG_URL to the direct endpoint")
        require(snapshot(prod_direct)["database"] == "fineract_default",
                "Direct target resolved to another database")
        promote(local, prod_direct, args.directory, args.confirm)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, psycopg.Error, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
