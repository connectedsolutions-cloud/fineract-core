package org.apache.fineract.portfolio.invoice.service;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceData;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceLine;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfig;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfigRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Slf4j
@RequiredArgsConstructor
public class InvoiceServiceImpl implements InvoiceService {

    private final InvoiceRepository invoiceRepository;
    private final PlatformSecurityContext platformSecurityContext;
    private final InvoiceLineMhCategoryBuilderService invoiceLineMhCategoryBuilderService;
    private final MhCompanyConfigRepository mhCompanyConfigRepository;
    private final LoanTransactionRepository loanTransactionRepository;

    @Override
    @Transactional
    public Invoice createDraft(InvoiceCreateRequest request) {
        log.info("INVOICE_DRAFT_CREATE_START loanTransactionId={} savingsTransactionId={} clientTransactionId={} lineCount={}",
                request.getLoanTransactionId(), request.getSavingsTransactionId(), request.getClientTransactionId(),
                request.getLines() != null ? request.getLines().size() : 0);
        validateTransactionLink(request.getLoanTransactionId(), request.getSavingsTransactionId(), request.getClientTransactionId());
        Office office = resolveCurrentUserOffice();
        String numeroControl = resolveNumeroControl(request, office);
        validateCreatePayload(request, numeroControl);

        Invoice invoice = Invoice.draft(request.getLoanTransactionId(), request.getSavingsTransactionId(), request.getClientTransactionId(),
                request.getVersion(), request.getAmbiente(), request.getTipoDte(), numeroControl,
                request.getCodigoGeneracion(), request.getTipoModelo(), request.getTipoOperacion(), request.getFecEmi(),
                request.getHorEmi(), request.getTipoMoneda());
        invoice.setContingency(request.getTipoContingencia(), request.getMotivoContin());
        MhCompanyConfig mhCompanyConfig = mhCompanyConfigRepository.findById(MhCompanyConfig.SINGLETON_ID).orElse(null);

        InvoiceIssuer issuer = InvoiceIssuer.empty();
        applyMhCompanyIssuerDefaults(issuer, mhCompanyConfig);
        if (StringUtils.isBlank(issuer.getNombre()) && StringUtils.isNotBlank(request.getEmisorNombre())) {
            issuer.setNombre(request.getEmisorNombre());
        }
        applyOfficeControlCodes(issuer, office);
        invoice.setIssuer(issuer);

        InvoiceReceiver receiver = InvoiceReceiver.empty();
        receiver.setNombre(request.getReceptorNombre());
        invoice.setReceiver(receiver);

        invoice.replaceLines(toDomainLines(request.getLines()));
        invoice.setSummary(buildSummaryFromLines(invoice.getLines()));
        Invoice saved = invoiceRepository.save(invoice);
        log.info("INVOICE_DRAFT_CREATE_OK invoiceId={} linkedLoanTx={} linkedSavingsTx={} linkedClientTx={} totalNoSuj={} totalExenta={} totalGravada={} totalPagar={}",
                saved.getId(), saved.getLoanTransactionId(), saved.getSavingsTransactionId(), saved.getClientTransactionId(),
                saved.getSummary() != null ? saved.getSummary().getTotalNoSuj() : null,
                saved.getSummary() != null ? saved.getSummary().getTotalExenta() : null,
                saved.getSummary() != null ? saved.getSummary().getTotalGravada() : null,
                saved.getSummary() != null ? saved.getSummary().getTotalPagar() : null);
        return saved;
    }

    @Override
    @Transactional
    public Invoice updateMetadata(Long invoiceId, InvoiceMetadataUpdateRequest request) {
        Invoice invoice = invoiceRepository.findById(invoiceId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found", invoiceId));
        if (StringUtils.isNotBlank(request.getFirmaElectronica())) {
            invoice.setFirmaElectronica(request.getFirmaElectronica());
        }
        if (invoice.getReceiver() != null) {
            invoice.getReceiver().setTipoDocumento(defaultTipoDocumento(request.getReceptorTipoDocumento()));
            if (StringUtils.isNotBlank(request.getReceptorNombre())) {
                invoice.getReceiver().setNombre(request.getReceptorNombre());
            }
            invoice.getReceiver().setDocId(request.getReceptorDocId());
            invoice.getReceiver().setNit(request.getReceptorNit());
            invoice.getReceiver().setNrc(request.getReceptorNrc());
            invoice.getReceiver().setCodActividad(request.getReceptorCodActividad());
            invoice.getReceiver().setDescActividad(request.getReceptorDescActividad());
            invoice.getReceiver().setNombreComercial(request.getReceptorNombreComercial());
            invoice.getReceiver().setDireccionDepartamento(request.getReceptorDireccionDepartamento());
            invoice.getReceiver().setDireccionMunicipio(request.getReceptorDireccionMunicipio());
            invoice.getReceiver().setDireccionComplemento(request.getReceptorDireccionComplemento());
            invoice.getReceiver().setCorreo(request.getReceptorCorreo());
            invoice.getReceiver().setTelefono(request.getReceptorTelefono());
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
    @Transactional(readOnly = true)
    public InvoiceData toInvoiceData(Invoice invoice) {
        InvoiceData data = InvoiceData.from(invoice);
        Long loanTransactionId = invoice.getLoanTransactionId();
        if (loanTransactionId == null) {
            return data;
        }
        loanTransactionRepository.findByIdWithLoanAndChargesPaid(loanTransactionId).ifPresent(txn -> enrichLoanContext(data, txn));
        return data;
    }

    private void enrichLoanContext(InvoiceData data, LoanTransaction txn) {
        Loan loan = txn.getLoan();
        if (loan == null) {
            return;
        }
        data.setLoanId(loan.getId());
        if (loan.getLoanProduct() != null) {
            data.setLoanProductName(loan.getLoanProduct().getName());
        }
        if (loan.getExternalId() != null && !loan.getExternalId().isEmpty()) {
            data.setLoanExternalId(loan.getExternalId().getValue());
        }
    }

    @Override
    @Transactional
    public void createDraftForLoanTransactionIfMissing(Long loanTransactionId) {
        if (loanTransactionId == null || invoiceRepository.findByLoanTransactionId(loanTransactionId).isPresent()) {
            log.debug("INVOICE_DRAFT_SKIP_LOAN loanTransactionId={} reason={}", loanTransactionId,
                    loanTransactionId == null ? "NULL_TRANSACTION_ID" : "ALREADY_EXISTS");
            return;
        }
        InvoiceCreateRequest request = new InvoiceCreateRequest();
        request.setLoanTransactionId(loanTransactionId);
        request.setVersion(3);
        request.setAmbiente("00");
        request.setTipoDte("03");
        request.setCodigoGeneracion(UUID.randomUUID().toString());
        request.setTipoModelo(1);
        request.setTipoOperacion(1);
        request.setFecEmi(DateUtils.getBusinessLocalDate());
        request.setHorEmi(java.time.LocalTime.now());
        request.setTipoMoneda("USD");
        request.setEmisorNombre("PENDING_ISSUER");
        request.setReceptorNombre("PENDING_RECEIVER");
        request.setLines(invoiceLineMhCategoryBuilderService.buildForLoanTransaction(loanTransactionId));
        log.info("INVOICE_DRAFT_BUILD_LOAN_LINE loanTransactionId={} generatedLineCount={}", loanTransactionId,
                request.getLines() != null ? request.getLines().size() : 0);
        createDraft(request);
    }

    @Override
    @Transactional
    public void createDraftForClientTransactionIfMissing(Long clientTransactionId) {
        if (clientTransactionId == null || invoiceRepository.findByClientTransactionId(clientTransactionId).isPresent()) {
            log.debug("INVOICE_DRAFT_SKIP_CLIENT clientTransactionId={} reason={}", clientTransactionId,
                    clientTransactionId == null ? "NULL_TRANSACTION_ID" : "ALREADY_EXISTS");
            return;
        }
        InvoiceCreateRequest request = new InvoiceCreateRequest();
        request.setClientTransactionId(clientTransactionId);
        request.setVersion(3);
        request.setAmbiente("00");
        request.setTipoDte("03");
        request.setCodigoGeneracion(UUID.randomUUID().toString());
        request.setTipoModelo(1);
        request.setTipoOperacion(1);
        request.setFecEmi(DateUtils.getBusinessLocalDate());
        request.setHorEmi(java.time.LocalTime.now());
        request.setTipoMoneda("USD");
        request.setEmisorNombre("PENDING_ISSUER");
        request.setReceptorNombre("PENDING_RECEIVER");
        request.setLines(invoiceLineMhCategoryBuilderService.buildForClientTransaction(clientTransactionId));
        log.info("INVOICE_DRAFT_BUILD_CLIENT_LINE clientTransactionId={} generatedLineCount={}", clientTransactionId,
                request.getLines() != null ? request.getLines().size() : 0);
        createDraft(request);
    }

    // Savings transaction invoice auto-draft hook is intentionally pending until a savings-side trigger invokes InvoiceService.

    private void validateCreatePayload(InvoiceCreateRequest request, String numeroControl) {
        if (!isUuidV4(request.getCodigoGeneracion())) {
            throw new PlatformDataIntegrityException("error.msg.invoice.codigo.generacion.invalid", "codigoGeneracion must be UUID v4",
                    request.getCodigoGeneracion());
        }
        if (StringUtils.length(numeroControl) != 31) {
            throw new PlatformDataIntegrityException("error.msg.invoice.numero.control.invalid", "numeroControl must be 31 chars",
                    numeroControl);
        }
    }

    private Office resolveCurrentUserOffice() {
        if (platformSecurityContext.getAuthenticatedUserIfPresent() == null) {
            return null;
        }
        return platformSecurityContext.getAuthenticatedUserIfPresent().getOffice();
    }

    private void applyOfficeControlCodes(InvoiceIssuer issuer, Office office) {
        if (issuer == null || office == null) {
            return;
        }
        issuer.setCodEstable(office.getMhCodEstable());
        issuer.setCodPuntoVenta(office.getMhCodPuntoVenta());
    }

    private void applyMhCompanyIssuerDefaults(InvoiceIssuer issuer, MhCompanyConfig config) {
        if (issuer == null || config == null) {
            return;
        }
        issuer.setNit(config.getNit());
        issuer.setNrc(config.getNrc());
        issuer.setNombre(config.getNombre());
        issuer.setNombreComercial(config.getNombreComercial());
        issuer.setCodActividad(config.getCodActividad());
        issuer.setDescActividad(config.getDescActividad());
        issuer.setTipoEstablecimiento(config.getTipoEstablecimiento());
        issuer.setDireccionDepartamento(config.getDireccionDepartamento());
        issuer.setDireccionMunicipio(config.getDireccionMunicipio());
        issuer.setDireccionComplemento(config.getDireccionComplemento());
        issuer.setTelefono(config.getTelefono());
        issuer.setCorreo(config.getCorreo());
    }

    private String resolveNumeroControl(InvoiceCreateRequest request, Office office) {
        if (StringUtils.isNotBlank(request.getNumeroControl())) {
            return request.getNumeroControl();
        }
        if (office == null) {
            throw new PlatformDataIntegrityException("error.msg.invoice.numero.control.office.missing",
                    "Cannot generate numeroControl without authenticated user office");
        }

        String codEstable = normalizeDigits(office.getMhCodEstable());
        String codPuntoVenta = normalizeDigits(office.getMhCodPuntoVenta());
        if (StringUtils.isBlank(codEstable) || StringUtils.isBlank(codPuntoVenta)) {
            throw new PlatformDataIntegrityException("error.msg.invoice.numero.control.office.codes.missing",
                    "Office must define mhCodEstable and mhCodPuntoVenta to generate numeroControl", office.getId());
        }

        String tipoDte = StringUtils.leftPad(normalizeDigits(request.getTipoDte()), 2, '0');
        tipoDte = StringUtils.right(tipoDte, 2);
        String establecimientoPunto = StringUtils.right(StringUtils.leftPad(codEstable, 4, '0'), 4)
                + StringUtils.right(StringUtils.leftPad(codPuntoVenta, 4, '0'), 4);
        String correlativo = StringUtils.leftPad(String.valueOf(nextCorrelativo()), 15, '0');
        correlativo = StringUtils.right(correlativo, 15);
        return "DTE-" + tipoDte + "-" + establecimientoPunto + "-" + correlativo;
    }

    private static String normalizeDigits(String value) {
        if (StringUtils.isBlank(value)) {
            return "";
        }
        return value.replaceAll("\\D+", "");
    }

    private long nextCorrelativo() {
        MhCompanyConfig config = mhCompanyConfigRepository.findByIdForUpdate(MhCompanyConfig.SINGLETON_ID)
                .orElseGet(MhCompanyConfig::emptySingleton);
        long lastValue = config.getLastDteCorrelativo() == null ? 0L : config.getLastDteCorrelativo();
        long nextValue = lastValue + 1;
        config.setLastDteCorrelativo(nextValue);
        mhCompanyConfigRepository.save(config);
        return nextValue;
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

    private String defaultTipoDocumento(String tipoDocumento) {
        return StringUtils.defaultIfBlank(tipoDocumento, "13");
    }
}

