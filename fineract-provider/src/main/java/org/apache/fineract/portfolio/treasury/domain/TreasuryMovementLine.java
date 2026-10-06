package org.apache.fineract.portfolio.treasury.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_treasury_movement_line")
@Getter
@Setter
@NoArgsConstructor
public class TreasuryMovementLine extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "movement_id", nullable = false)
    private TreasuryMovement movement;

    @ManyToOne(optional = false)
    @JoinColumn(name = "bank_account_id", nullable = false)
    private TreasuryBankAccount bankAccount;

    @Column(name = "direction", nullable = false, length = 10)
    private String direction;

    @Column(name = "amount", nullable = false, scale = 6, precision = 19)
    private BigDecimal amount;

    @Column(name = "balance_after", nullable = false, scale = 6, precision = 19)
    private BigDecimal balanceAfter;
}
