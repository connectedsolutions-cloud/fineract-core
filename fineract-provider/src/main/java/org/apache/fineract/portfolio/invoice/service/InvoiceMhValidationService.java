package org.apache.fineract.portfolio.invoice.service;

import org.apache.fineract.portfolio.invoice.domain.Invoice;

public interface InvoiceMhValidationService {

    Invoice submitMhValidationByInvoiceId(Long invoiceId);

    Invoice submitMhValidationByLoanTransactionId(Long loanTransactionId);

    Invoice submitMhValidationBySavingsTransactionId(Long savingsTransactionId);

    Invoice submitMhValidationByClientTransactionId(Long clientTransactionId);
}
