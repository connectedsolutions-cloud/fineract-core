package org.apache.fineract.portfolio.treasury.domain;

import jakarta.persistence.LockModeType;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface TreasuryBankAccountRepository extends JpaRepository<TreasuryBankAccount, Long> {

    Optional<TreasuryBankAccount> findByGlAccountId(Long glAccountId);

    boolean existsByGlAccountId(Long glAccountId);

    List<TreasuryBankAccount> findByActiveTrueOrderByNameAsc();

    List<TreasuryBankAccount> findAllByOrderByNameAsc();

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select bank from TreasuryBankAccount bank where bank.id = :id")
    Optional<TreasuryBankAccount> findByIdForUpdate(@Param("id") Long id);
}
