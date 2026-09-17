/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import lombok.Getter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransaction;

@Entity
@Table(name = "m_share_account_yield_settlement")
@Getter
public class ShareAccountYieldSettlement extends AbstractPersistableCustom<Long> {
    @ManyToOne(optional = false)
    @JoinColumn(name = "share_account_id")
    private ShareAccount shareAccount;

    @OneToOne(optional = false)
    @JoinColumn(name = "savings_transaction_id")
    private SavingsAccountTransaction savingsTransaction;

    @Column(name = "settlement_date", nullable = false)
    private LocalDate settlementDate;

    @Column(name = "amount", nullable = false, precision = 19, scale = 6)
    private BigDecimal amount;

    @Column(name = "reference", length = 100)
    private String reference;

    protected ShareAccountYieldSettlement() {}

    public ShareAccountYieldSettlement(ShareAccount shareAccount, SavingsAccountTransaction savingsTransaction, LocalDate settlementDate,
            BigDecimal amount, String reference) {
        this.shareAccount = shareAccount;
        this.savingsTransaction = savingsTransaction;
        this.settlementDate = settlementDate;
        this.amount = amount;
        this.reference = reference;
    }
}
