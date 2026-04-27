package org.apache.fineract.portfolio.invoice.service;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class InvoiceServiceImpl implements InvoiceService {

    private final InvoiceRepository invoiceRepository;

    @Override
    @Transactional
    public Invoice createDraft(InvoiceCreateRequest request) {
        validateTransactionLink(request.getLoanTransactionId(), request.getSavingsTransactionId(), request.getClientTransactionId());
        validateCreatePayload(request);

        Invoice invoice = Invoice.draft(request.getLoanTransactionId(), request.getSavingsTransactionId(), request.getClientTransactionId(),
                request.getVersion(), request.getAmbiente(), request.getTipoDte(), request.getNumeroControl(),
                request.getCodigoGeneracion(), request.getTipoModelo(), request.getTipoOperacion(), request.getFecEmi(),
                request.getHorEmi(), request.getTipoMoneda());
        invoice.setContingency(request.getTipoContingencia(), request.getMotivoContin());

        InvoiceIssuer issuer = InvoiceIssuer.empty();
        issuer.setNombre(request.getEmisorNombre());
        invoice.setIssuer(issuer);

        InvoiceReceiver receiver = InvoiceReceiver.empty();
        receiver.setNombre(request.getReceptorNombre());
        invoice.setReceiver(receiver);

        invoice.replaceLines(toDomainLines(request.getLines()));
        invoice.setSummary(buildSummaryFromLines(invoice.getLines()));
        return invoiceRepository.save(invoice);
    }

    @Override
    @Transactional
    public Invoice updateMetadata(Long invoiceId, InvoiceMetadataUpdateRequest request) {
        Invoice invoice = invoiceRepository.findById(invoiceId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found", invoiceId));
        if (StringUtils.isNotBlank(request.getFirmaElectronica())) {
            invoice.setFirmaElectronica(request.getFirmaElectronica());
        }
        invoice.setAuthorityData(request.getAuthorityStatus(), request.getAuthorityMessage(), request.getSelloRecibido(),
                LocalDateTime.now());
        if (StringUtils.isNotBlank(request.getNextStatus())) {
            invoice.setStatus(InvoiceStatus.valueOf(request.getNextStatus()));
        }
        validateByState(invoice);
        return invoiceRepository.save(invoice);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<Invoice> findById(Long id) {
        return invoiceRepository.findById(id);
    }

    @Override
    @Transactional(readOnly = true)
    public Optional<Invoice> findByTransaction(Long loanTransactionId, Long savingsTransactionId, Long clientTransactionId) {
        if (loanTransactionId != null) {
            return invoiceRepository.findByLoanTransactionId(loanTransactionId);
        }
        if (savingsTransactionId != null) {
            return invoiceRepository.findBySavingsTransactionId(savingsTransactionId);
        }
        if (clientTransactionId != null) {
            return invoiceRepository.findByClientTransactionId(clientTransactionId);
        }
        return Optional.empty();
    }

    @Override
    @Transactional
    public void createDraftForLoanTransactionIfMissing(Long loanTransactionId) {
        if (loanTransactionId == null || invoiceRepository.findByLoanTransactionId(loanTransactionId).isPresent()) {
            return;
        }
        InvoiceCreateRequest request = new InvoiceCreateRequest();
        request.setLoanTransactionId(loanTransactionId);
        request.setVersion(3);
        request.setAmbiente("00");
        request.setTipoDte("03");
        request.setNumeroControl(("DTE-" + loanTransactionId + "-" + System.currentTimeMillis()).substring(0, 31));
        request.setCodigoGeneracion(UUID.randomUUID().toString());
        request.setTipoModelo(1);
        request.setTipoOperacion(1);
        request.setFecEmi(DateUtils.getBusinessLocalDate());
        request.setHorEmi(java.time.LocalTime.now());
        request.setTipoMoneda("USD");
        request.setEmisorNombre("PENDING_ISSUER");
        request.setReceptorNombre("PENDING_RECEIVER");
        request.setLines(new ArrayList<>());
        createDraft(request);
    }

    @Override
    @Transactional
    public void createDraftForClientTransactionIfMissing(Long clientTransactionId) {
        if (clientTransactionId == null || invoiceRepository.findByClientTransactionId(clientTransactionId).isPresent()) {
            return;
        }
        InvoiceCreateRequest request = new InvoiceCreateRequest();
        request.setClientTransactionId(clientTransactionId);
        request.setVersion(3);
        request.setAmbiente("00");
        request.setTipoDte("03");
        request.setNumeroControl(("DTE-CLI-" + clientTransactionId + "-" + System.currentTimeMillis()).substring(0, 31));
        request.setCodigoGeneracion(UUID.randomUUID().toString());
        request.setTipoModelo(1);
        request.setTipoOperacion(1);
        request.setFecEmi(DateUtils.getBusinessLocalDate());
        request.setHorEmi(java.time.LocalTime.now());
        request.setTipoMoneda("USD");
        request.setEmisorNombre("PENDING_ISSUER");
        request.setReceptorNombre("PENDING_RECEIVER");
        request.setLines(new ArrayList<>());
        createDraft(request);
    }

    private void validateCreatePayload(InvoiceCreateRequest request) {
        if (!isUuidV4(request.getCodigoGeneracion())) {
            throw new PlatformDataIntegrityException("error.msg.invoice.codigo.generacion.invalid", "codigoGeneracion must be UUID v4",
                    request.getCodigoGeneracion());
        }
        if (StringUtils.length(request.getNumeroControl()) != 31) {
            throw new PlatformDataIntegrityException("error.msg.invoice.numero.control.invalid", "numeroControl must be 31 chars",
                    request.getNumeroControl());
        }
    }

    private void validateByState(Invoice invoice) {
        if (invoice.getStatus() == InvoiceStatus.GENERATED) {
            if (invoice.getIssuer() == null || invoice.getReceiver() == null || invoice.getSummary() == null
                    || invoice.getLines().isEmpty()) {
                throw new PlatformDataIntegrityException("error.msg.invoice.generated.invalid",
                        "GENERATED invoice requires emisor, receptor, lines and resumen", invoice.getId());
            }
        }
        if (invoice.getStatus() == InvoiceStatus.SIGNED && StringUtils.isBlank(invoice.getFirmaElectronica())) {
            throw new PlatformDataIntegrityException("error.msg.invoice.signed.invalid", "SIGNED invoice requires firmaElectronica",
                    invoice.getId());
        }
        if (invoice.getStatus() == InvoiceStatus.ACCEPTED && StringUtils.isBlank(invoice.getSelloRecibido())) {
            throw new PlatformDataIntegrityException("error.msg.invoice.accepted.invalid", "ACCEPTED invoice requires selloRecibido",
                    invoice.getId());
        }
    }

    private List<InvoiceLine> toDomainLines(List<InvoiceLineRequest> lines) {
        List<InvoiceLine> out = new ArrayList<>();
        if (lines == null) {
            return out;
        }
        for (InvoiceLineRequest line : lines) {
            out.add(InvoiceLine.of(line.getNumItem(), line.getTipoItem(), line.getCantidad(), line.getUniMedida(), line.getDescripcion(),
                    line.getPrecioUni(), line.getMontoDescu(), line.getVentaNoSuj(), line.getVentaExenta(), line.getVentaGravada(),
                    line.getTributos(), line.getNoGravado()));
        }
        return out;
    }

    private InvoiceSummary buildSummaryFromLines(List<InvoiceLine> lines) {
        BigDecimal totalNoSuj = BigDecimal.ZERO;
        BigDecimal totalExenta = BigDecimal.ZERO;
        BigDecimal totalGravada = BigDecimal.ZERO;
        BigDecimal descuentos = BigDecimal.ZERO;
        BigDecimal subTotalVentas = BigDecimal.ZERO;
        for (InvoiceLine line : lines) {
            totalNoSuj = totalNoSuj.add(line.getVentaNoSuj());
            totalExenta = totalExenta.add(line.getVentaExenta());
            totalGravada = totalGravada.add(line.getVentaGravada());
            descuentos = descuentos.add(line.getMontoDescu());
            subTotalVentas = subTotalVentas.add(line.getPrecioUni());
        }
        BigDecimal subTotal = totalNoSuj.add(totalExenta).add(totalGravada).subtract(descuentos);
        return InvoiceSummary.basic(totalNoSuj, totalExenta, totalGravada, subTotalVentas, BigDecimal.ZERO, BigDecimal.ZERO, descuentos,
                subTotal, subTotal, subTotal);
    }

    private void validateTransactionLink(Long loanTransactionId, Long savingsTransactionId, Long clientTransactionId) {
        int count = 0;
        if (loanTransactionId != null) {
            count++;
        }
        if (savingsTransactionId != null) {
            count++;
        }
        if (clientTransactionId != null) {
            count++;
        }
        if (count != 1) {
            throw new PlatformDataIntegrityException("error.msg.invoice.transaction.link.invalid",
                    "Exactly one transaction reference must be provided", count);
        }
    }

    private boolean isUuidV4(String value) {
        try {
            UUID uuid = UUID.fromString(value);
            return uuid.version() == 4;
        } catch (Exception e) {
            return false;
        }
    }
}

