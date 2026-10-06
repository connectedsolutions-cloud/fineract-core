package org.apache.fineract.portfolio.treasury.domain;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToMany;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.staff.domain.Staff;

@Entity
@Table(name = "m_treasury_movement")
@Getter
@Setter
@NoArgsConstructor
public class TreasuryMovement extends AbstractPersistableCustom<Long> {

    @Column(name = "business_date", nullable = false)
    private LocalDate businessDate;

    @Column(name = "value_date", nullable = false)
    private LocalDate valueDate;

    @ManyToOne(optional = false)
    @JoinColumn(name = "office_id", nullable = false)
    private Office office;

    @Column(name = "movement_type", nullable = false, length = 40)
    private String movementType;

    @Column(name = "amount", nullable = false, scale = 6, precision = 19)
    private BigDecimal amount;

    @Column(name = "currency_code", nullable = false, length = 3)
    private String currencyCode;

    @Column(name = "status", nullable = false, length = 20)
    private String status;

    @Column(name = "journal_owner", nullable = false, length = 20)
    private String journalOwner;

    @Column(name = "journal_transaction_id", length = 50)
    private String journalTransactionId;

    @Column(name = "ref_num", length = 20)
    private String refNum;

    @Column(name = "bank_reference", length = 100)
    private String bankReference;

    @Column(name = "payee_name", length = 200)
    private String payeeName;

    @ManyToOne
    @JoinColumn(name = "staff_id")
    private Staff staff;

    @Column(name = "note", length = 500)
    private String note;

    @ManyToOne
    @JoinColumn(name = "counter_gl_account_id")
    private GLAccount counterGlAccount;

    @Column(name = "reverses_movement_id")
    private Long reversesMovementId;

    @Column(name = "created_by_user_id")
    private Long createdByUserId;

    @Column(name = "created_on")
    private OffsetDateTime createdOn;

    @OneToMany(mappedBy = "movement", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<TreasuryMovementLine> lines = new ArrayList<>();

    @OneToMany(mappedBy = "movement", cascade = CascadeType.ALL, orphanRemoval = true)
    private List<TreasuryMovementLink> links = new ArrayList<>();
}
