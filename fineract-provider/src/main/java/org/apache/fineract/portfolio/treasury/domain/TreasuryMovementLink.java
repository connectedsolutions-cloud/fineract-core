package org.apache.fineract.portfolio.treasury.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_treasury_movement_link", uniqueConstraints = {
        @UniqueConstraint(name = "uk_treasury_link_entity", columnNames = { "link_type", "entity_id" }) })
@Getter
@Setter
@NoArgsConstructor
public class TreasuryMovementLink extends AbstractPersistableCustom<Long> {

    @ManyToOne(optional = false)
    @JoinColumn(name = "movement_id", nullable = false)
    private TreasuryMovement movement;

    @Column(name = "link_type", nullable = false, length = 40)
    private String linkType;

    @Column(name = "entity_id", nullable = false)
    private Long entityId;
}
