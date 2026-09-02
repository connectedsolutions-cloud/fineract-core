package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface MhCompanyConfigRepository extends JpaRepository<MhCompanyConfig, Long> {

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT c FROM MhCompanyConfig c WHERE c.id = :id")
    Optional<MhCompanyConfig> findByIdForUpdate(@Param("id") Long id);
}
