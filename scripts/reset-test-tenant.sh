#!/usr/bin/env bash
# Capture, restore, or recreate a local non-default Fineract test tenant.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-}"
TENANT="${2:-}"
if [[ $# -ge 2 ]]; then shift 2; else set --; fi

BASELINE_DIR="${TENANT_BASELINE_DIR:-$ROOT/.tenant-baselines}"
STATE_FILE=""
CONFIRM=""
FINERACT_HOST="${FINERACT_HOST:-127.0.0.1}"
FINERACT_PORT="${FINERACT_PORT:-8443}"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/reset-test-tenant.sh status TENANT [options]
  ./scripts/reset-test-tenant.sh capture TENANT [options]
  ./scripts/reset-test-tenant.sh reset TENANT --confirm TENANT:DATABASE [options]
  ./scripts/reset-test-tenant.sh recreate TENANT --confirm TENANT:DATABASE [options]

Actions:
  status    Show the registered database, core counts, and baseline metadata.
  capture   Save an exact pre-cycle PostgreSQL baseline. Fineract must be stopped.
  reset     Replace the tenant database with its captured baseline.
  recreate  Replace the tenant database with an empty database for Liquibase.

Options:
  --baseline-dir DIR  Baseline directory (default: fineract-core/.tenant-baselines).
  --state-file FILE   Sync SQLite state to snapshot/archive with the tenant.
  --confirm VALUE     Required exact TENANT:DATABASE confirmation for reset/recreate.
  --help              Show this help.

Connection settings come from PG* variables or fineract-core/.env. This tool
refuses tenant "default", non-local PostgreSQL hosts, unregistered databases,
and destructive actions while Fineract is listening on port 8443.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-dir)
      [[ $# -ge 2 ]] || die "--baseline-dir requires a value"
      BASELINE_DIR="$2"
      shift 2
      ;;
    --state-file)
      [[ $# -ge 2 ]] || die "--state-file requires a value"
      STATE_FILE="$2"
      shift 2
      ;;
    --confirm)
      [[ $# -ge 2 ]] || die "--confirm requires a value"
      CONFIRM="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

if [[ "$ACTION" == "--help" || "$ACTION" == "-h" || -z "$ACTION" ]]; then
  usage
  [[ -n "$ACTION" ]] && exit 0 || exit 2
fi
[[ "$ACTION" =~ ^(status|capture|reset|recreate)$ ]] || die "Unknown action: $ACTION"
[[ "$TENANT" =~ ^[A-Za-z][A-Za-z0-9_-]*$ ]] || die "Invalid tenant identifier: $TENANT"
[[ "$TENANT" != "default" ]] || die "The default tenant can never be reset by this tool"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

JDBC_URL="${FINERACT_HIKARI_JDBC_URL:-}"
if [[ -n "$JDBC_URL" && "$JDBC_URL" =~ jdbc:postgresql://([^:/]+):?([0-9]*)/([^?]+) ]]; then
  PGHOST="${PGHOST:-${BASH_REMATCH[1]}}"
  [[ -z "${BASH_REMATCH[2]}" ]] || PGPORT="${PGPORT:-${BASH_REMATCH[2]}}"
  TENANTS_DB="${TENANTS_DB:-${BASH_REMATCH[3]}}"
fi

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${PGUSER:-${FINERACT_HIKARI_USERNAME:-postgres}}"
export PGPASSWORD="${PGPASSWORD:-${FINERACT_HIKARI_PASSWORD:-}}"
TENANTS_DB="${TENANTS_DB:-fineract_tenants}"
MAINT_DB="${PGMAINTDB:-postgres}"

case "$PGHOST" in
  localhost|127.0.0.1|::1) ;;
  *) die "Refusing non-local PostgreSQL host: $PGHOST" ;;
esac

for command in psql pg_dump pg_restore dropdb createdb shasum; do
  command -v "$command" >/dev/null 2>&1 || die "Required command not found: $command"
done

registry_row="$(psql -X -v ON_ERROR_STOP=1 -d "$TENANTS_DB" -AtF '|' -c \
  "SELECT c.schema_server, c.schema_server_port, c.schema_name
     FROM tenants t
     JOIN tenant_server_connections c ON c.id = t.oltp_id
    WHERE t.identifier = '$TENANT';")"
[[ -n "$registry_row" ]] || die "Tenant is not registered: $TENANT"
[[ "$(printf '%s\n' "$registry_row" | wc -l | tr -d ' ')" == "1" ]] || die "Tenant registry is ambiguous: $TENANT"

IFS='|' read -r REGISTERED_HOST REGISTERED_PORT DB_NAME <<<"$registry_row"
[[ "$DB_NAME" =~ ^fineract_[A-Za-z0-9_]+$ ]] || die "Unsafe registered database name: $DB_NAME"
[[ "$DB_NAME" != "fineract_default" && "$DB_NAME" != "$TENANTS_DB" ]] || die "Protected database: $DB_NAME"
case "$REGISTERED_HOST" in
  localhost|127.0.0.1|::1) ;;
  *) die "Refusing tenant registered on non-local host: $REGISTERED_HOST" ;;
esac
[[ -z "$REGISTERED_PORT" || "$REGISTERED_PORT" == "$PGPORT" ]] || \
  die "Registry port $REGISTERED_PORT does not match admin port $PGPORT"

SAFE_TENANT="${TENANT//-/_}"
DUMP_FILE="$BASELINE_DIR/${SAFE_TENANT}.dump"
META_FILE="$BASELINE_DIR/${SAFE_TENANT}.meta"
COUNTS_FILE="$BASELINE_DIR/${SAFE_TENANT}.counts"
BASELINE_STATE_FILE="$BASELINE_DIR/${SAFE_TENANT}.state.sqlite3"

fineract_is_running() {
  if command -v nc >/dev/null 2>&1; then
    nc -z "$FINERACT_HOST" "$FINERACT_PORT" >/dev/null 2>&1
  else
    (echo >/dev/tcp/"$FINERACT_HOST"/"$FINERACT_PORT") >/dev/null 2>&1
  fi
}

require_fineract_stopped() {
  fineract_is_running && die "Fineract is listening on ${FINERACT_HOST}:${FINERACT_PORT}; stop it before $ACTION"
}

database_exists() {
  [[ "$(psql -X -d "$MAINT_DB" -Atqc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")" == "1" ]]
}

write_counts() {
  local output="$1"
  psql -X -v ON_ERROR_STOP=1 -d "$DB_NAME" -AtF '=' <<'SQL' >"$output"
SELECT 'databasechangelog', COUNT(*) FROM databasechangelog
UNION ALL SELECT 'm_client', COUNT(*) FROM m_client
UNION ALL SELECT 'm_staff', COUNT(*) FROM m_staff
UNION ALL SELECT 'm_loan', COUNT(*) FROM m_loan
UNION ALL SELECT 'm_savings_account', COUNT(*) FROM m_savings_account
UNION ALL SELECT 'm_share_account', COUNT(*) FROM m_share_account
ORDER BY 1;
SQL
}

archive_state() {
  [[ -n "$STATE_FILE" ]] || return 0
  [[ -f "$STATE_FILE" ]] || return 0
  local stamp archive
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  archive="${STATE_FILE}.reset-${stamp}"
  mv "$STATE_FILE" "$archive"
  echo "Archived sync state: $archive"
}

restore_baseline_state() {
  [[ -n "$STATE_FILE" ]] || return 0
  if [[ -f "$BASELINE_STATE_FILE" ]]; then
    mkdir -p "$(dirname "$STATE_FILE")"
    cp "$BASELINE_STATE_FILE" "$STATE_FILE"
    echo "Restored baseline sync state: $STATE_FILE"
  fi
}

replace_with_empty_database() {
  psql -X -v ON_ERROR_STOP=1 -d "$MAINT_DB" -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" >/dev/null
  dropdb --if-exists --force --maintenance-db="$MAINT_DB" "$DB_NAME"
  createdb --maintenance-db="$MAINT_DB" "$DB_NAME"
}

case "$ACTION" in
  status)
    echo "Tenant: $TENANT"
    echo "Database: $DB_NAME"
    echo "PostgreSQL: $PGHOST:$PGPORT"
    echo "Fineract listening: $(fineract_is_running && echo yes || echo no)"
    if database_exists; then
      temp_counts="$(mktemp)"
      trap 'rm -f "$temp_counts"' EXIT
      write_counts "$temp_counts"
      echo "Current counts:"
      sed 's/^/  /' "$temp_counts"
    else
      echo "Current database: missing"
    fi
    if [[ -f "$DUMP_FILE" && -f "$META_FILE" && -f "$COUNTS_FILE" ]]; then
      echo "Baseline: $DUMP_FILE"
      sed 's/^/  /' "$META_FILE"
      echo "Baseline counts:"
      sed 's/^/  /' "$COUNTS_FILE"
    else
      echo "Baseline: none"
    fi
    ;;

  capture)
    require_fineract_stopped
    database_exists || die "Tenant database does not exist: $DB_NAME"
    [[ ! -e "$DUMP_FILE" && ! -e "$META_FILE" && ! -e "$COUNTS_FILE" ]] || \
      die "Baseline already exists for $TENANT; archive it explicitly before replacing it"
    mkdir -p "$BASELINE_DIR"
    temp_dump="$(mktemp "$BASELINE_DIR/.${SAFE_TENANT}.dump.XXXXXX")"
    temp_counts="$(mktemp "$BASELINE_DIR/.${SAFE_TENANT}.counts.XXXXXX")"
    trap 'rm -f "$temp_dump" "$temp_counts"' EXIT
    pg_dump --format=custom --no-owner --no-privileges --file="$temp_dump" "$DB_NAME"
    write_counts "$temp_counts"
    dump_sha="$(shasum -a 256 "$temp_dump" | awk '{print $1}')"
    mv "$temp_dump" "$DUMP_FILE"
    mv "$temp_counts" "$COUNTS_FILE"
    {
      echo "tenant=$TENANT"
      echo "database=$DB_NAME"
      echo "host=$PGHOST"
      echo "port=$PGPORT"
      echo "captured_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      echo "sha256=$dump_sha"
      echo "state_present=$([[ -n "$STATE_FILE" && -f "$STATE_FILE" ]] && echo yes || echo no)"
    } >"$META_FILE"
    if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
      cp "$STATE_FILE" "$BASELINE_STATE_FILE"
    fi
    echo "Captured baseline: $DUMP_FILE"
    echo "Confirmation for reset: $TENANT:$DB_NAME"
    ;;

  reset)
    require_fineract_stopped
    [[ "$CONFIRM" == "$TENANT:$DB_NAME" ]] || die "Expected --confirm $TENANT:$DB_NAME"
    [[ -f "$DUMP_FILE" && -f "$META_FILE" && -f "$COUNTS_FILE" ]] || die "No complete baseline for $TENANT"
    [[ "$(awk -F= '$1=="tenant" {print $2}' "$META_FILE")" == "$TENANT" ]] || die "Baseline tenant mismatch"
    [[ "$(awk -F= '$1=="database" {print $2}' "$META_FILE")" == "$DB_NAME" ]] || die "Baseline database mismatch"
    expected_sha="$(awk -F= '$1=="sha256" {print $2}' "$META_FILE")"
    actual_sha="$(shasum -a 256 "$DUMP_FILE" | awk '{print $1}')"
    [[ -n "$expected_sha" && "$actual_sha" == "$expected_sha" ]] || die "Baseline checksum mismatch"
    archive_state
    replace_with_empty_database
    pg_restore --exit-on-error --no-owner --no-privileges --dbname="$DB_NAME" "$DUMP_FILE"
    temp_counts="$(mktemp)"
    trap 'rm -f "$temp_counts"' EXIT
    write_counts "$temp_counts"
    cmp -s "$COUNTS_FILE" "$temp_counts" || {
      echo "Expected counts:" >&2
      cat "$COUNTS_FILE" >&2
      echo "Restored counts:" >&2
      cat "$temp_counts" >&2
      die "Restored tenant counts do not match the baseline"
    }
    restore_baseline_state
    echo "Reset complete: $TENANT -> $DB_NAME"
    echo "Restart Fineract before using the tenant."
    ;;

  recreate)
    require_fineract_stopped
    [[ "$CONFIRM" == "$TENANT:$DB_NAME" ]] || die "Expected --confirm $TENANT:$DB_NAME"
    archive_state
    replace_with_empty_database
    echo "Recreated empty database: $DB_NAME"
    echo "Restart Fineract with Liquibase enabled, verify the tenant, then stop it and run capture."
    ;;
esac
