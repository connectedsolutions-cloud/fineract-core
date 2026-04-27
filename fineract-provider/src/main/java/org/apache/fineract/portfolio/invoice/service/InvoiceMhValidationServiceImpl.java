package org.apache.fineract.portfolio.invoice.service;

import java.time.LocalDateTime;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.invoice.domain.InvoiceIssuer;
import org.apache.fineract.portfolio.invoice.domain.InvoiceReceiver;
import org.apache.fineract.portfolio.invoice.domain.InvoiceRepository;
import org.apache.fineract.portfolio.invoice.domain.InvoiceStatus;
import org.apache.fineract.portfolio.invoice.domain.InvoiceSummary;
import org.apache.fineract.portfolio.invoice.mh.DteJsonBuilder;
import org.apache.fineract.portfolio.invoice.mh.InvoiceOfficeResolver;
import org.apache.fineract.portfolio.invoice.mh.MhFirmaCredentialResolver;
import org.apache.fineract.portfolio.invoice.mh.MhFirmaCredentials;
import org.apache.fineract.portfolio.invoice.mh.MhSubmitResult;
import org.apache.fineract.portfolio.invoice.mh.MhValidationFirmaRestClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class InvoiceMhValidationServiceImpl implements InvoiceMhValidationService {

    private final InvoiceRepository invoiceRepository;
    private final InvoiceOfficeResolver invoiceOfficeResolver;
    private final MhFirmaCredentialResolver mhFirmaCredentialResolver;
    private final DteJsonBuilder dteJsonBuilder;
    private final MhValidationFirmaRestClient mhValidationFirmaRestClient;

    @Override
    @Transactional
    public Invoice submitMhValidationByInvoiceId(Long invoiceId) {
        Invoice invoice = invoiceRepository.findById(invoiceId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found", invoiceId));
        return submitInternal(invoice);
    }

    @Override
    @Transactional
    public Invoice submitMhValidationByLoanTransactionId(Long loanTransactionId) {
        Invoice invoice = invoiceRepository.findByLoanTransactionId(loanTransactionId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found for loan transaction",
                        loanTransactionId));
        return submitInternal(invoice);
    }

    @Override
    @Transactional
    public Invoice submitMhValidationBySavingsTransactionId(Long savingsTransactionId) {
        Invoice invoice = invoiceRepository.findBySavingsTransactionId(savingsTransactionId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found for savings transaction",
                        savingsTransactionId));
        return submitInternal(invoice);
    }

    @Override
    @Transactional
    public Invoice submitMhValidationByClientTransactionId(Long clientTransactionId) {
        Invoice invoice = invoiceRepository.findByClientTransactionId(clientTransactionId)
                .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.invoice.not.found", "Invoice not found for client transaction",
                        clientTransactionId));
        return submitInternal(invoice);
    }

    private Invoice submitInternal(Invoice invoice) {
        assertReadyForMhSubmit(invoice);
        if ("PENDING".equalsIgnoreCase(StringUtils.trimToEmpty(invoice.getMhValidationStatus()))) {
            throw new PlatformDataIntegrityException("error.msg.mh.already.pending", "MH validation already pending for this invoice",
                    invoice.getId());
        }
        Long officeId = invoiceOfficeResolver.resolveOfficeId(invoice);
        MhFirmaCredentials credentials = mhFirmaCredentialResolver.resolve(officeId);
        MhSubmitResult result = mhValidationFirmaRestClient.submitValidate(dteJsonBuilder.buildDteJsonObject(invoice), credentials);
        if (!result.isSuccess()) {
            throw new PlatformDataIntegrityException("error.msg.mh.submit.failed", result.getErrorMessage(), invoice.getId());
        }
        invoice.markMhSubmitPending(result.getJobId(), LocalDateTime.now());
        invoice.setStatus(InvoiceStatus.SUBMITTED);
        return invoiceRepository.save(invoice);
    }

    private void assertReadyForMhSubmit(Invoice invoice) {
        if (invoice.getStatus() != InvoiceStatus.GENERATED && invoice.getStatus() != InvoiceStatus.SIGNED) {
            throw new PlatformDataIntegrityException("error.msg.mh.invoice.status.invalid",
                    "Invoice must be GENERATED or SIGNED before MH validation", invoice.getId());
        }
        InvoiceIssuer issuer = invoice.getIssuer();
        InvoiceReceiver receiver = invoice.getReceiver();
        InvoiceSummary summary = invoice.getSummary();
        if (issuer == null || receiver == null || summary == null || invoice.getLines().isEmpty()) {
            throw new PlatformDataIntegrityException("error.msg.mh.invoice.incomplete",
                    "Invoice must have issuer, receptor, resumen and at least one line", invoice.getId());
        }
        if (StringUtils.isBlank(issuer.getNit())) {
            throw new PlatformDataIntegrityException("error.msg.mh.invoice.issuer.nit.missing", "Issuer NIT is required on the invoice", invoice.getId());
        }
    }
}
