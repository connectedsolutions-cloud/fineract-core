package org.apache.fineract.portfolio.invoice.service;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.apache.fineract.portfolio.invoice.mh.DteJsonBuilder;
import org.apache.fineract.portfolio.invoice.mh.InvoiceOfficeResolver;
import org.apache.fineract.portfolio.invoice.mh.MhFirmaCredentialResolver;
import org.apache.fineract.portfolio.invoice.mh.MhFirmaCredentials;
import org.apache.fineract.portfolio.invoice.mh.MhValidationFirmaRestClient;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class InvoiceMhValidationServiceImplTest {

    @Mock
    private InvoiceRepository invoiceRepository;
    @Mock
    private InvoiceOfficeResolver invoiceOfficeResolver;
    @Mock
    private MhFirmaCredentialResolver mhFirmaCredentialResolver;
    @Mock
    private DteJsonBuilder dteJsonBuilder;
    @Mock
    private MhValidationFirmaRestClient mhValidationFirmaRestClient;

    private InvoiceMhValidationServiceImpl service;

    @BeforeEach
    void setup() {
        service = new InvoiceMhValidationServiceImpl(invoiceRepository, invoiceOfficeResolver, mhFirmaCredentialResolver, dteJsonBuilder,
                mhValidationFirmaRestClient);
    }

    @Test
    void submitMhValidationFailsWhenIssuerRequiredFieldIsMissing() {
        Invoice invoice = validGeneratedInvoice();
        invoice.getIssuer().setNrc(null);
        when(invoiceRepository.findById(1L)).thenReturn(Optional.of(invoice));
        when(invoiceOfficeResolver.resolveOfficeId(invoice)).thenReturn(1L);
        when(mhFirmaCredentialResolver.resolve(1L)).thenReturn(new MhFirmaCredentials("06141212001014", null, null, null));

        assertThrows(PlatformDataIntegrityException.class, () -> service.submitMhValidationByInvoiceId(1L));
        verifyNoInteractions(dteJsonBuilder, mhValidationFirmaRestClient);
    }

    private Invoice validGeneratedInvoice() {
        Invoice invoice = Invoice.draft(10L, null, null, 3, "00", "03", "DTE-03-00010001-000000000000001", UUID.randomUUID().toString(), 1,
                1, LocalDate.now(), LocalTime.NOON, "USD");
        InvoiceIssuer issuer = InvoiceIssuer.empty();
        issuer.setNit("06141212001014");
        issuer.setNrc("12345");
        issuer.setNombre("Credesal SA de CV");
        issuer.setCodActividad("62010");
        issuer.setDescActividad("Servicios financieros");
        issuer.setNombreComercial(null);
        issuer.setTipoEstablecimiento("01");
        issuer.setDireccionDepartamento("06");
        issuer.setDireccionMunicipio("14");
        issuer.setDireccionComplemento("Distrito Centro, Calle 1");
        issuer.setTelefono("22223333");
        issuer.setCorreo("facturacion@credesal.com");
        invoice.setIssuer(issuer);

        InvoiceReceiver receiver = InvoiceReceiver.empty();
        receiver.setNombre("CONSUMIDOR FINAL");
        invoice.setReceiver(receiver);

        invoice.replaceLines(List.of(InvoiceLine.of(1, 1, BigDecimal.ONE, 99, "SERVICIO", BigDecimal.TEN, BigDecimal.ZERO, BigDecimal.ZERO,
                BigDecimal.ZERO, BigDecimal.TEN, "[]", BigDecimal.ZERO)));
        invoice.setSummary(InvoiceSummary.basic(BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.TEN, BigDecimal.TEN, BigDecimal.ZERO,
                BigDecimal.ZERO, BigDecimal.ZERO, BigDecimal.TEN, BigDecimal.TEN, BigDecimal.TEN));
        invoice.setStatus(InvoiceStatus.GENERATED);
        return invoice;
    }
}
