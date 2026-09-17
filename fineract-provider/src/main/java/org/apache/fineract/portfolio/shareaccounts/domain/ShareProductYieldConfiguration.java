/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import lombok.Getter;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.portfolio.shareproducts.domain.ShareProduct;

@Entity
@Table(name = "m_share_product_yield_config")
@Getter
public class ShareProductYieldConfiguration {

    @Id
    @Column(name = "product_id")
    private Long productId;

    @OneToOne(optional = false)
    @JoinColumn(name = "product_id", insertable = false, updatable = false)
    private ShareProduct product;

    @Column(name = "enabled", nullable = false)
    private boolean enabled;

    @Column(name = "annual_rate", nullable = false, precision = 10, scale = 6)
    private BigDecimal annualRate;

    @Column(name = "accrual_start_date", nullable = false)
    private LocalDate accrualStartDate;

    @ManyToOne(optional = false)
    @JoinColumn(name = "expense_gl_account_id")
    private GLAccount expenseAccount;

    @ManyToOne(optional = false)
    @JoinColumn(name = "payable_gl_account_id")
    private GLAccount payableAccount;

    protected ShareProductYieldConfiguration() {}

    public ShareProductYieldConfiguration(ShareProduct product, boolean enabled, BigDecimal annualRate, LocalDate accrualStartDate,
            GLAccount expenseAccount, GLAccount payableAccount) {
        this.product = product;
        this.productId = product.getId();
        update(enabled, annualRate, accrualStartDate, expenseAccount, payableAccount);
    }

    public void update(boolean enabled, BigDecimal annualRate, LocalDate accrualStartDate, GLAccount expenseAccount,
            GLAccount payableAccount) {
        this.enabled = enabled;
        this.annualRate = annualRate;
        this.accrualStartDate = accrualStartDate;
        this.expenseAccount = expenseAccount;
        this.payableAccount = payableAccount;
    }
}
