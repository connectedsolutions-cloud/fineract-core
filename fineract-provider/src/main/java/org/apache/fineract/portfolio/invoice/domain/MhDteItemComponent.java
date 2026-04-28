package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import org.apache.fineract.infrastructure.core.domain.AbstractAuditableCustom;
import org.apache.fineract.portfolio.charge.domain.Charge;

@Entity
@Table(name = "m_mh_dte_item_component")
public class MhDteItemComponent extends AbstractAuditableCustom {

    @Column(name = "name", nullable = false, length = 255)
    private String name;

    @Enumerated(EnumType.STRING)
    @Column(name = "dte_amount_type", length = 32)
    private MhDteAmountType dteAmountType;

    @ManyToOne
    @JoinColumn(name = "charge_id")
    private Charge charge;

    @Enumerated(EnumType.STRING)
    @Column(name = "loan_component", length = 32)
    private MhDteLoanComponent loanComponent;

    @Column(name = "client_type", length = 255)
    private String clientType;

    @Column(name = "client_type_key", nullable = false, length = 256)
    private String clientTypeKey;

    @Column(name = "target_uq", nullable = false, length = 100)
    private String targetUq;

    protected MhDteItemComponent() {}

    public static MhDteItemComponent create(String name, MhDteAmountType dteAmountType, Charge charge, MhDteLoanComponent loanComponent,
            String clientType, String clientTypeKey, String targetUq) {
        MhDteItemComponent e = new MhDteItemComponent();
        e.name = name;
        e.dteAmountType = dteAmountType;
        e.charge = charge;
        e.loanComponent = loanComponent;
        e.clientType = clientType;
        e.clientTypeKey = clientTypeKey;
        e.targetUq = targetUq;
        return e;
    }

    public void update(String name, MhDteAmountType dteAmountType, Charge charge, MhDteLoanComponent loanComponent, String clientType,
            String clientTypeKey, String targetUq) {
        this.name = name;
        this.dteAmountType = dteAmountType;
        this.charge = charge;
        this.loanComponent = loanComponent;
        this.clientType = clientType;
        this.clientTypeKey = clientTypeKey;
        this.targetUq = targetUq;
    }

    public String getName() {
        return name;
    }

    public MhDteAmountType getDteAmountType() {
        return dteAmountType;
    }

    public Charge getCharge() {
        return charge;
    }

    public MhDteLoanComponent getLoanComponent() {
        return loanComponent;
    }

    public String getClientType() {
        return clientType;
    }

    public String getClientTypeKey() {
        return clientTypeKey;
    }

    public String getTargetUq() {
        return targetUq;
    }
}
