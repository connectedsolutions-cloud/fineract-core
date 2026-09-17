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

@Entity
@Table(name = "m_share_account_yield_accrual")
@Getter
public class ShareAccountYieldAccrual extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "share_account_id")
    private ShareAccount shareAccount;

    @OneToOne(optional = false)
    @JoinColumn(name = "share_transaction_id")
    private ShareAccountTransaction shareTransaction;

    @Column(name = "accrual_date", nullable = false)
    private LocalDate accrualDate;

    @Column(name = "entry_type", nullable = false, length = 20)
    private String entryType;

    @Column(name = "base_amount", nullable = false, precision = 19, scale = 6)
    private BigDecimal baseAmount;

    @Column(name = "annual_rate", nullable = false, precision = 10, scale = 6)
    private BigDecimal annualRate;

    @Column(name = "day_count_basis", nullable = false)
    private int dayCountBasis;

    @Column(name = "accrued_amount", nullable = false, precision = 19, scale = 8)
    private BigDecimal accruedAmount;

    @Column(name = "booked_amount", nullable = false, precision = 19, scale = 6)
    private BigDecimal bookedAmount;

    @Column(name = "source_reference", length = 100)
    private String sourceReference;

    @Column(name = "imported", nullable = false)
    private boolean imported;

    protected ShareAccountYieldAccrual() {}

    public ShareAccountYieldAccrual(ShareAccount shareAccount, ShareAccountTransaction shareTransaction, LocalDate accrualDate,
            String entryType,
            BigDecimal baseAmount, BigDecimal annualRate, int dayCountBasis, BigDecimal accruedAmount, BigDecimal bookedAmount,
            String sourceReference, boolean imported) {
        this.shareAccount = shareAccount;
        this.shareTransaction = shareTransaction;
        this.accrualDate = accrualDate;
        this.entryType = entryType;
        this.baseAmount = baseAmount;
        this.annualRate = annualRate;
        this.dayCountBasis = dayCountBasis;
        this.accruedAmount = accruedAmount;
        this.bookedAmount = bookedAmount;
        this.sourceReference = sourceReference;
        this.imported = imported;
    }
}
