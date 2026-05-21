package org.apache.fineract.portfolio.invoice.service;

import java.util.Optional;
import org.apache.fineract.portfolio.invoice.data.InvoiceCreateRequest;
import org.apache.fineract.portfolio.invoice.data.InvoiceData;
import org.apache.fineract.portfolio.invoice.data.InvoiceMetadataUpdateRequest;
import org.apache.fineract.portfolio.invoice.domain.Invoice;

public interface InvoiceService {

    Invoice createDraft(InvoiceCreateRequest request);

    Invoice updateMetadata(Long invoiceId, InvoiceMetadataUpdateRequest request);

    Optional<Invoice> findById(Long id);

    Optional<Invoice> findByTransaction(Long loanTransactionId, Long savingsTransactionId, Long clientTransactionId);

    void createDraftForLoanTransactionIfMissing(Long loanTransactionId);

    void createDraftForClientTransactionIfMissing(Long clientTransactionId);

    InvoiceData toInvoiceData(Invoice invoice);
}

