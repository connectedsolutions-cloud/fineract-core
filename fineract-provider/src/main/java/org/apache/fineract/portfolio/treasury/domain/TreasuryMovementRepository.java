package org.apache.fineract.portfolio.treasury.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TreasuryMovementRepository extends JpaRepository<TreasuryMovement, Long> {

    @Query("""
            select distinct movement from TreasuryMovement movement
            join movement.lines line
            where line.bankAccount.id = :bankAccountId
            order by movement.id desc
            """)
    List<TreasuryMovement> findForBank(@Param("bankAccountId") Long bankAccountId);

    @Query("""
            select count(line) from TreasuryMovementLine line
            where line.bankAccount.id = :bankAccountId
            """)
    long countLines(@Param("bankAccountId") Long bankAccountId);

    @Query("""
            select count(line) from TreasuryMovementLine line
            where line.bankAccount.id = :bankAccountId
            and line.movement.movementType = 'opening_balance'
            and line.movement.status = 'posted'
            """)
    long countPostedOpeningLines(@Param("bankAccountId") Long bankAccountId);
}
