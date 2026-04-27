package org.apache.fineract.portfolio.invoice.domain;

import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface InvoiceRepository extends JpaRepository<Invoice, Long> {

    Optional<Invoice> findByLoanTransactionId(Long loanTransactionId);

    Optional<Invoice> findBySavingsTransactionId(Long savingsTransactionId);

    Optional<Invoice> findByClientTransactionId(Long clientTransactionId);

    Optional<Invoice> findByCodigoGeneracionAndNumeroControl(String codigoGeneracion, String numeroControl);
}

