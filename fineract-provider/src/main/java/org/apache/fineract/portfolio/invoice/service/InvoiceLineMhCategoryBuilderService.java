package org.apache.fineract.portfolio.invoice.service;

import java.util.List;
import org.apache.fineract.portfolio.invoice.data.InvoiceLineRequest;

public interface InvoiceLineMhCategoryBuilderService {

    List<InvoiceLineRequest> buildForLoanTransaction(Long loanTransactionId);

    List<InvoiceLineRequest> buildForClientTransaction(Long clientTransactionId);
}

