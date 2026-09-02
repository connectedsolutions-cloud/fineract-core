package org.apache.fineract.portfolio.invoice.service;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfig;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfigRepository;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class InvoiceServiceImplTest {

    @Mock
    private InvoiceRepository invoiceRepository;
    @Mock
    private PlatformSecurityContext platformSecurityContext;
    @Mock
    private InvoiceLineMhCategoryBuilderService invoiceLineMhCategoryBuilderService;
    @Mock
    private MhCompanyConfigRepository mhCompanyConfigRepository;
    @Mock
    private LoanTransactionRepository loanTransactionRepository;

    private InvoiceServiceImpl service;

    @BeforeEach
    void setup() {
        service = new InvoiceServiceImpl(invoiceRepository, platformSecurityContext, invoiceLineMhCategoryBuilderService,
                mhCompanyConfigRepository, loanTransactionRepository);
    }

    @Test
    void createDraftFailsWhenNumberControlLengthInvalid() {
        InvoiceCreateRequest request = validRequest();
        request.setNumeroControl("SHORT");

        assertThrows(PlatformDataIntegrityException.class, () -> service.createDraft(request));
    }

    @Test
    void createDraftSucceedsWithValidPayload() {
        InvoiceCreateRequest request = validRequest();
        when(invoiceRepository.save(any(Invoice.class))).thenAnswer(inv -> inv.getArgument(0));
        assertDoesNotThrow(() -> service.createDraft(request));
    }

    @Test
    void createDraftPopulatesIssuerFromMhCompanyConfig() {
        InvoiceCreateRequest request = validRequest();
        MhCompanyConfig config = mhCompanyConfig();
        when(mhCompanyConfigRepository.findById(MhCompanyConfig.SINGLETON_ID)).thenReturn(Optional.of(config));
        when(invoiceRepository.save(any(Invoice.class))).thenAnswer(inv -> inv.getArgument(0));

        Invoice invoice = service.createDraft(request);

        org.junit.jupiter.api.Assertions.assertEquals("06141212001014", invoice.getIssuer().getNit());
        org.junit.jupiter.api.Assertions.assertEquals("12345", invoice.getIssuer().getNrc());
        org.junit.jupiter.api.Assertions.assertEquals("Credesal SA de CV", invoice.getIssuer().getNombre());
        org.junit.jupiter.api.Assertions.assertEquals("62010", invoice.getIssuer().getCodActividad());
        org.junit.jupiter.api.Assertions.assertEquals("Servicios financieros", invoice.getIssuer().getDescActividad());
        org.junit.jupiter.api.Assertions.assertEquals("01", invoice.getIssuer().getTipoEstablecimiento());
        org.junit.jupiter.api.Assertions.assertEquals("06", invoice.getIssuer().getDireccionDepartamento());
        org.junit.jupiter.api.Assertions.assertEquals("14", invoice.getIssuer().getDireccionMunicipio());
        org.junit.jupiter.api.Assertions.assertEquals("Distrito Centro, Calle 1", invoice.getIssuer().getDireccionComplemento());
        org.junit.jupiter.api.Assertions.assertEquals("22223333", invoice.getIssuer().getTelefono());
        org.junit.jupiter.api.Assertions.assertEquals("facturacion@credesal.com", invoice.getIssuer().getCorreo());
    }

    @Test
    void createDraftAllowsNullNombreComercial() {
        InvoiceCreateRequest request = validRequest();
        MhCompanyConfig config = mhCompanyConfig();
        config.setNombreComercial(null);
        when(mhCompanyConfigRepository.findById(MhCompanyConfig.SINGLETON_ID)).thenReturn(Optional.of(config));
        when(invoiceRepository.save(any(Invoice.class))).thenAnswer(inv -> inv.getArgument(0));

        Invoice invoice = service.createDraft(request);

        org.junit.jupiter.api.Assertions.assertEquals("Credesal SA de CV", invoice.getIssuer().getNombre());
        org.junit.jupiter.api.Assertions.assertNull(invoice.getIssuer().getNombreComercial());
    }

    @Test
    void updateMetadataRequiresSignatureForSignedStatus() {
        InvoiceCreateRequest request = validRequest();
        when(invoiceRepository.save(any(Invoice.class))).thenAnswer(inv -> inv.getArgument(0));
        Invoice invoice = service.createDraft(request);
        invoice.setStatus(InvoiceStatus.SIGNED);
        when(invoiceRepository.findById(1L)).thenReturn(Optional.of(invoice));

        InvoiceMetadataUpdateRequest metadata = new InvoiceMetadataUpdateRequest();
        metadata.setNextStatus("SIGNED");
        assertThrows(PlatformDataIntegrityException.class, () -> service.updateMetadata(1L, metadata));
    }

    @Test
    void updateMetadataMapsExtendedReceptorFieldsAndDefaultsTipoDocumento() {
        InvoiceCreateRequest request = validRequest();
        when(invoiceRepository.save(any(Invoice.class))).thenAnswer(inv -> inv.getArgument(0));
        Invoice invoice = service.createDraft(request);
        when(invoiceRepository.findById(1L)).thenReturn(Optional.of(invoice));

        InvoiceMetadataUpdateRequest metadata = new InvoiceMetadataUpdateRequest();
        metadata.setReceptorNombre("Nuevo Receptor");
        metadata.setReceptorDocId("01234567-8");
        metadata.setReceptorNit("06141212001014");
        metadata.setReceptorNrc("1234567");
        metadata.setReceptorCodActividad("62010");
        metadata.setReceptorDescActividad("Servicios");
        metadata.setReceptorNombreComercial("Comercial");
        metadata.setReceptorDireccionDepartamento("06");
        metadata.setReceptorDireccionMunicipio("14");
        metadata.setReceptorDireccionComplemento("San Salvador");
        metadata.setReceptorCorreo("cliente@correo.com");
        metadata.setReceptorTelefono("70000000");

        Invoice updated = service.updateMetadata(1L, metadata);

        assertEquals("13", updated.getReceiver().getTipoDocumento());
        assertEquals("Nuevo Receptor", updated.getReceiver().getNombre());
        assertEquals("01234567-8", updated.getReceiver().getDocId());
        assertEquals("06141212001014", updated.getReceiver().getNit());
        assertEquals("1234567", updated.getReceiver().getNrc());
        assertEquals("62010", updated.getReceiver().getCodActividad());
        assertEquals("Servicios", updated.getReceiver().getDescActividad());
        assertEquals("Comercial", updated.getReceiver().getNombreComercial());
        assertEquals("06", updated.getReceiver().getDireccionDepartamento());
        assertEquals("14", updated.getReceiver().getDireccionMunicipio());
        assertEquals("San Salvador", updated.getReceiver().getDireccionComplemento());
        assertEquals("cliente@correo.com", updated.getReceiver().getCorreo());
        assertEquals("70000000", updated.getReceiver().getTelefono());
    }

    private InvoiceCreateRequest validRequest() {
        InvoiceLineRequest line = new InvoiceLineRequest();
        line.setNumItem(1);
        line.setTipoItem(1);
        line.setCantidad(java.math.BigDecimal.ONE);
        line.setDescripcion("Item");
        line.setPrecioUni(java.math.BigDecimal.TEN);
        line.setVentaGravada(java.math.BigDecimal.TEN);

        InvoiceCreateRequest request = new InvoiceCreateRequest();
        request.setLoanTransactionId(10L);
        request.setVersion(3);
        request.setAmbiente("00");
        request.setTipoDte("03");
        request.setNumeroControl("1234567890123456789012345678901");
        request.setCodigoGeneracion(UUID.randomUUID().toString());
        request.setTipoModelo(1);
        request.setTipoOperacion(1);
        request.setFecEmi(LocalDate.now());
        request.setHorEmi(LocalTime.NOON);
        request.setTipoMoneda("USD");
        request.setEmisorNombre("EMISOR");
        request.setReceptorNombre("RECEPTOR");
        request.setLines(List.of(line));
        return request;
    }

    private MhCompanyConfig mhCompanyConfig() {
        MhCompanyConfig config = MhCompanyConfig.emptySingleton();
        config.setNit("06141212001014");
        config.setNrc("12345");
        config.setNombre("Credesal SA de CV");
        config.setNombreComercial("Credesal");
        config.setCodActividad("62010");
        config.setDescActividad("Servicios financieros");
        config.setTipoEstablecimiento("01");
        config.setDireccionDepartamento("06");
        config.setDireccionMunicipio("14");
        config.setDireccionComplemento("Distrito Centro, Calle 1");
        config.setTelefono("22223333");
        config.setCorreo("facturacion@credesal.com");
        return config;
    }
}
