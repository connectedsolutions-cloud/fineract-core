package org.apache.fineract.portfolio.treasury.domain;

import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

public interface TreasuryMovementLinkRepository extends JpaRepository<TreasuryMovementLink, Long> {

    Optional<TreasuryMovementLink> findByLinkTypeAndEntityId(String linkType, Long entityId);
}
