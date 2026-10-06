package org.apache.fineract.portfolio.treasury.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.organisation.office.domain.Office;

@Entity
@Table(name = "m_treasury_bank_account")
@Getter
@Setter
@NoArgsConstructor
public class TreasuryBankAccount extends AbstractPersistableCustom<Long> {

    @Column(name = "name", nullable = false, length = 100)
    private String name;

    @ManyToOne(optional = false)
    @JoinColumn(name = "gl_account_id", nullable = false, unique = true)
    private GLAccount glAccount;

    @Column(name = "currency_code", nullable = false, length = 3)
    private String currencyCode;

    @ManyToOne
    @JoinColumn(name = "office_id")
    private Office office;

    @Column(name = "active", nullable = false)
    private boolean active = true;

    @Column(name = "external_account_reference", length = 100)
    private String externalAccountReference;

    @Column(name = "alias", length = 100)
    private String alias;

    @Column(name = "balance", nullable = false, scale = 6, precision = 19)
    private BigDecimal balance = BigDecimal.ZERO;

    @Column(name = "created_by_user_id")
    private Long createdByUserId;

    @Column(name = "created_on")
    private OffsetDateTime createdOn;
}
