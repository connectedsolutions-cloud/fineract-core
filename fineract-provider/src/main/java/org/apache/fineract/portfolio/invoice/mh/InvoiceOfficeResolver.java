package org.apache.fineract.portfolio.invoice.mh;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.portfolio.client.domain.ClientTransaction;
import org.apache.fineract.portfolio.client.domain.ClientTransactionRepository;
import org.apache.fineract.portfolio.invoice.domain.Invoice;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransactionRepository;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransaction;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransactionRepository;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class InvoiceOfficeResolver {

    private final LoanTransactionRepository loanTransactionRepository;
    private final ClientTransactionRepository clientTransactionRepository;
    private final SavingsAccountTransactionRepository savingsAccountTransactionRepository;

    public Long resolveOfficeId(Invoice invoice) {
        if (invoice.getLoanTransactionId() != null) {
            LoanTransaction tx = loanTransactionRepository.findById(invoice.getLoanTransactionId())
                    .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.loan.transaction.not.found",
                            "Loan transaction not found", invoice.getLoanTransactionId()));
            return tx.getOffice().getId();
        }
        if (invoice.getClientTransactionId() != null) {
            ClientTransaction tx = clientTransactionRepository.findById(invoice.getClientTransactionId())
                    .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.client.transaction.not.found",
                            "Client transaction not found", invoice.getClientTransactionId()));
            return tx.getClient().officeId();
        }
        if (invoice.getSavingsTransactionId() != null) {
            SavingsAccountTransaction tx = savingsAccountTransactionRepository.findById(invoice.getSavingsTransactionId())
                    .orElseThrow(() -> new PlatformDataIntegrityException("error.msg.savings.transaction.not.found",
                            "Savings transaction not found", invoice.getSavingsTransactionId()));
            return tx.getOfficeId();
        }
        throw new PlatformDataIntegrityException("error.msg.invoice.no.transaction",
                "Invoice has no linked transaction for MH office resolution", invoice.getId());
    }
}
