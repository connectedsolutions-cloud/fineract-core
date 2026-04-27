package org.apache.fineract.portfolio.invoice.service;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class InvoiceServiceImplTest {

    @Mock
    private InvoiceRepository invoiceRepository;

    private InvoiceServiceImpl service;

    @BeforeEach
    void setup() {
        service = new InvoiceServiceImpl(invoiceRepository);
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
}

