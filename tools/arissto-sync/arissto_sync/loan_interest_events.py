"""Read-only evidence and conservative classification for one loan revision."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from .arissto import select_rows, source_connection
from .config import SourceConfig


def _amount(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def classify_interest_revision(evidence: dict[str, Any]) -> str:
    """Return a source event family, never permission to post a target event."""
    before, after = evidence["closes"]
    total_drop = _amount(before["SALDO_INTERES"]) - _amount(after["SALDO_INTERES"])
    overdue_drop = _amount(before["SALDO_VENCIDO_INTERES"]) - _amount(after["SALDO_VENCIDO_INTERES"])
    paid_change = _amount(after["SALDO_PAGADO_INTERES"]) - _amount(before["SALDO_PAGADO_INTERES"])
    pending_edits = [a for a in evidence["audits"] if a["FieldName"] == "SALDO_INTERES_PENDIENTE"]
    pending_increase = any(_amount(a["NewValue"]) > _amount(a["OldValue"]) for a in pending_edits)
    date_edits = [a for a in evidence["audits"] if a["FieldName"] == "FECHA_ULTIMO_PAGOINT"]
    if (len(date_edits) != 1 or evidence["movement_count"]
            or evidence["same_close_revision_count"] != 1 or paid_change != 0
            or not evidence["plan_unchanged"]):
        return "mixed_or_unresolved"
    if pending_increase and total_drop == 0 and overdue_drop > 0:
        return "pending_interest_due_relief"
    if not pending_increase and total_drop > 0:
        return "interest_balance_recalculation"
    return "mixed_or_unresolved"


def _plan_signature(rows: list[dict[str, Any]]) -> str:
    normalized = [[str(r[k]) for k in ("NO_CUOTA", "FECHA_PAGO", "MONTO_CAPITAL", "MONTO_INTERES", "CUOTA")]
                  for r in rows]
    return hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()


def inspect_interest_revision(source: SourceConfig, loan_id: int, revision_id: int) -> dict[str, Any]:
    if loan_id <= 0 or revision_id <= 0:
        raise ValueError("Loan and revision IDs must be positive")
    with source_connection(source) as conn:
        revisions = select_rows(conn, """
            SELECT ID_CREDITO,ID_REESTRUCTURACION,DT_CREO,ID_CIERRE_DIARIO
            FROM dbo.CRD_REESTRUCTURACION
            WHERE ID_CREDITO=? AND ID_REESTRUCTURACION=?
        """, (loan_id, revision_id))
        if len(revisions) != 1:
            raise ValueError("Source loan revision was not found")
        revision = revisions[0]
        recorded = revision["DT_CREO"]
        loan_keys = select_rows(conn, """
            SELECT ID_SOLICITUD_CREDITO,ID_SUCURSAL,ID_EMPRESA,ID_LINEA_CREDITO,
                   ID_SOCIO,ID_PRESTAMO_NO
            FROM dbo.CRD_CARTERA WHERE ID_CREDITO=?
        """, (loan_id,))
        if len(loan_keys) != 1:
            raise ValueError("Source portfolio loan was not found")
        key = "+".join(str(v) for v in loan_keys[0].values())
        audits = select_rows(conn, """
            SELECT IDAudit,FieldName,OldValue,NewValue,UpdateDate
            FROM dbo.Audit
            WHERE TableName='CRD_CARTERA' AND PrimaryKeyValue=?
              AND UpdateDate>=? AND UpdateDate<=?
              AND FieldName IN ('FECHA_ULTIMO_PAGOINT','SALDO_INTERES',
                                'SALDO_VENCIDO_INTERES','SALDO_INTERES_PENDIENTE')
            ORDER BY UpdateDate,IDAudit
        """, (key, recorded - timedelta(seconds=5), recorded + timedelta(seconds=30)))
        close_id = revision["ID_CIERRE_DIARIO"]
        same_close_revisions = select_rows(conn, """
            SELECT ID_REESTRUCTURACION FROM dbo.CRD_REESTRUCTURACION
            WHERE ID_CREDITO=? AND ID_CIERRE_DIARIO=?
        """, (loan_id, close_id))
        closes = select_rows(conn, """
            SELECT TOP 2 ID_CIERRE_DIARIO,SALDO_INTERES,SALDO_VENCIDO_INTERES,
                   SALDO_PAGADO_INTERES,SALDO_VENCIDO_CAPITAL
            FROM dbo.CRD_HISTORICO_DIARIO
            WHERE ID_CREDITO=? AND ID_CIERRE_DIARIO<=?
            ORDER BY ID_CIERRE_DIARIO DESC
        """, (loan_id, close_id))
        if len(closes) != 2 or closes[0]["ID_CIERRE_DIARIO"] != close_id:
            raise ValueError("Adjacent source close evidence is missing")
        movements = select_rows(conn, """
            SELECT ID_MOVIMIENTO_CARTERA,MONTO_CAPITAL,MONTO_INTERES,REVERSION
            FROM dbo.CRD_MOVIMIENTOS_CARTERA
            WHERE ID_CREDITO=? AND ID_CIERRE_DIARIO=?
        """, (loan_id, close_id))
        before_rows = select_rows(conn, """
            SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES,CUOTA
            FROM dbo.CRD_PLAN_PAGO WHERE ID_REESTRUCTURACION=?
            ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
        """, (revision_id,))
        successors = select_rows(conn, """
            SELECT TOP 1 ID_REESTRUCTURACION
            FROM dbo.CRD_REESTRUCTURACION
            WHERE ID_CREDITO=? AND (DT_CREO>? OR
                  (DT_CREO=? AND ID_REESTRUCTURACION>?))
            ORDER BY DT_CREO,ID_REESTRUCTURACION
        """, (loan_id, recorded, recorded, revision_id))
        if successors:
            after_rows = select_rows(conn, """
                SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES,CUOTA
                FROM dbo.CRD_PLAN_PAGO WHERE ID_REESTRUCTURACION=?
                ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
            """, (successors[0]["ID_REESTRUCTURACION"],))
        else:
            after_rows = select_rows(conn, """
                SELECT NO_CUOTA,FECHA_PAGO,MONTO_CAPITAL,MONTO_INTERES,CUOTA
                FROM dbo.CRD_PLAN_PAGO WHERE ID_CREDITO=?
                ORDER BY NO_CUOTA,FECHA_PAGO,ID_PLAN_PAGO
            """, (loan_id,))
    before_hash = _plan_signature(before_rows) if before_rows else None
    after_hash = _plan_signature(after_rows) if after_rows else None
    evidence = {
        "source_loan_id": loan_id, "revision_id": revision_id,
        "recorded_at": recorded.isoformat(), "close_id": close_id,
        "audits": [{**a, "UpdateDate": a["UpdateDate"].isoformat()} for a in audits],
        "closes": [closes[1], closes[0]],
        "movement_count": len(movements),
        "movement_ids": [m["ID_MOVIMIENTO_CARTERA"] for m in movements],
        "same_close_revision_count": len(same_close_revisions),
        "before_plan_hash": before_hash, "after_plan_hash": after_hash,
        "plan_unchanged": before_hash is not None and before_hash == after_hash,
    }
    evidence["classification"] = classify_interest_revision(evidence)
    evidence["target_write_allowed"] = False
    return evidence
