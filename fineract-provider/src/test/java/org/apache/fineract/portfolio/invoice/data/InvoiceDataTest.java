package org.apache.fineract.portfolio.invoice.data;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.UUID;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.junit.jupiter.api.Test;

class InvoiceDataTest {

    @Test
    void fromMapsIssuerLinesAndSummaryForPrint() {
        String codigoGeneracion = UUID.randomUUID().toString();
        Invoice invoice = Invoice.draft(10L, null, null, 3, "00", "03", "DTE-03-00010001-000000000000001", codigoGeneracion, 1, 1,
                LocalDate.of(2026, 5, 21), LocalTime.of(14, 30), "USD");
        invoice.setStatus(InvoiceStatus.ACCEPTED);
        invoice.setAuthorityData(null, null, "SELLO123", null);

        InvoiceIssuer issuer = InvoiceIssuer.empty();
        issuer.setNombre("CREDESAL");
        issuer.setNit("06141401141057");
        issuer.setNrc("123456");
        issuer.setCodActividad("64190");
        issuer.setDescActividad("Servicios financieros");
        issuer.setDireccionDepartamento("14");
        issuer.setDireccionMunicipio("01");
        issuer.setDireccionComplemento("Casa Matriz");
        issuer.setTelefono("2222-2222");
        issuer.setCorreo("facturacion@credesal.com");
        issuer.setCodEstableMh("M001");
        issuer.setCodPuntoVentaMh("P001");
        invoice.setIssuer(issuer);

        InvoiceLine line = InvoiceLine.of(1, 1, BigDecimal.ONE, 99, "Cuota capital", BigDecimal.valueOf(100), BigDecimal.ZERO,
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.valueOf(100), "[]", BigDecimal.ZERO);
        invoice.replaceLines(List.of(line));

        InvoiceSummary summary = InvoiceSummary.basic(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.valueOf(100), BigDecimal.valueOf(100),
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.valueOf(100), BigDecimal.valueOf(100),
                BigDecimal.valueOf(100));
        invoice.setSummary(summary);

        InvoiceData data = InvoiceData.from(invoice);

        assertEquals("03", data.getTipoDte());
        assertEquals("00", data.getAmbiente());
        assertEquals(LocalTime.of(14, 30), data.getHorEmi());
        assertEquals("USD", data.getTipoMoneda());
        assertEquals("SELLO123", data.getSelloRecibido());
        assertEquals("CREDESAL", data.getEmisorNombre());
        assertEquals("06141401141057", data.getEmisorNit());
        assertEquals("M001", data.getEmisorCodEstableMh());
        assertNotNull(data.getLines());
        assertEquals(1, data.getLines().size());
        assertEquals("Cuota capital", data.getLines().get(0).getDescripcion());
        assertEquals(0, BigDecimal.valueOf(100).compareTo(data.getTotalPagar()));
    }
}
