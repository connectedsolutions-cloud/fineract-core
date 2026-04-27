package org.apache.fineract.portfolio.invoice.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDateTime;
import org.junit.jupiter.api.Test;

class InvoiceMhWebhookApplyTest {

    @Test
    void applySuccessSetsTransmissionAndAcceptsWhenProcesado() {
        Invoice inv = Invoice.draft(1L, null, null, 3, "00", "03", "DTE-01-M001P001-000000000000001", "550E8400-E29B-41D4-A716-446655440000", 1, 1,
                java.time.LocalDate.now(), java.time.LocalTime.NOON, "USD");
        LocalDateTime t = LocalDateTime.of(2026, 4, 26, 10, 0);
        inv.applyMhWebhookSuccess("tx-1", "PROCESADO", "JWS...", "{\"sello\":\"x\"}", t);
        assertEquals("SUCCESS", inv.getMhValidationStatus());
        assertEquals("tx-1", inv.getMhTransmissionId());
        assertEquals("PROCESADO", inv.getMhTransmissionStatus());
        assertEquals("JWS...", inv.getMhDocumentoJws());
        assertEquals(InvoiceStatus.ACCEPTED, inv.getStatus());
    }

    @Test
    void applyFailureSetsRejected() {
        Invoice inv = Invoice.draft(1L, null, null, 3, "00", "03", "DTE-01-M001P001-000000000000002", "650E8400-E29B-41D4-A716-446655440001", 1, 1,
                java.time.LocalDate.now(), java.time.LocalTime.NOON, "USD");
        LocalDateTime t = LocalDateTime.of(2026, 4, 26, 11, 0);
        inv.applyMhWebhookFailure("mh error", t);
        assertEquals("FAILED", inv.getMhValidationStatus());
        assertEquals(InvoiceStatus.REJECTED, inv.getStatus());
    }
}
