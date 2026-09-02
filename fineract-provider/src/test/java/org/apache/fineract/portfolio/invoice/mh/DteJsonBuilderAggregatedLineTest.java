package org.apache.fineract.portfolio.invoice.mh;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Map;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.junit.jupiter.api.Test;

class DteJsonBuilderAggregatedLineTest {

    @SuppressWarnings("unchecked")
    @Test
    void buildsCuerpoDocumentoFromSingleAggregatedLine() {
        Invoice invoice = Invoice.draft(11L, null, null, 3, "00", "03", "DTE-03-00010001-000000000000011",
                "1c2f8cfe-1522-460d-9a7f-d2f3ab16d630", 1, 1, LocalDate.now(), LocalTime.NOON, "USD");

        InvoiceLine line = InvoiceLine.of(1, 1, BigDecimal.ONE, 99, "LOAN_TRANSACTION", new BigDecimal("120.00"), BigDecimal.ZERO,
                new BigDecimal("20.00"), new BigDecimal("0.00"), new BigDecimal("100.00"), "[]", BigDecimal.ZERO);
        invoice.replaceLines(java.util.List.of(line));
        invoice.setSummary(InvoiceSummary.basic(new BigDecimal("20.00"), BigDecimal.ZERO, new BigDecimal("100.00"),
                new BigDecimal("120.00"), BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, new BigDecimal("120.00"),
                new BigDecimal("120.00"), new BigDecimal("120.00")));

        DteJsonBuilder builder = new DteJsonBuilder();
        Map<String, Object> json = builder.buildDteJsonObject(invoice);

        java.util.List<Map<String, Object>> body = (java.util.List<Map<String, Object>>) json.get("cuerpoDocumento");
        assertEquals(1, body.size());
        assertEquals(new BigDecimal("20.00"), body.get(0).get("ventaNoSuj"));
        assertEquals(new BigDecimal("100.00"), body.get(0).get("ventaGravada"));
    }
}
