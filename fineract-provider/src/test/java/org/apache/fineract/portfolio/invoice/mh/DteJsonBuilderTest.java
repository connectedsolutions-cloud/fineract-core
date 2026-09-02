package org.apache.fineract.portfolio.invoice.mh;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Map;
import java.util.UUID;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.junit.jupiter.api.Test;

class DteJsonBuilderTest {

    @Test
    void buildReceptorDefaultsTipoDocumentoToDuiCode() {
        DteJsonBuilder builder = new DteJsonBuilder();
        Invoice invoice = Invoice.draft(1L, null, null, 3, "00", "03", "DTE-03-00010001-000000000000001", UUID.randomUUID().toString(), 1,
                1, LocalDate.now(), LocalTime.NOON, "USD");

        InvoiceReceiver receiver = InvoiceReceiver.empty();
        receiver.setNombre("Cliente Demo");
        receiver.setDocId("01234567-8");
        receiver.setNit("06141212001014");
        receiver.setNrc("1234567");
        receiver.setCorreo("cliente@correo.com");
        invoice.setReceiver(receiver);

        Map<String, Object> dteObject = builder.buildDteJsonObject(invoice);
        @SuppressWarnings("unchecked")
        Map<String, Object> receptor = (Map<String, Object>) dteObject.get("receptor");

        assertEquals("13", receptor.get("tipoDocumento"));
        assertEquals("01234567-8", receptor.get("numDocumento"));
    }
}
