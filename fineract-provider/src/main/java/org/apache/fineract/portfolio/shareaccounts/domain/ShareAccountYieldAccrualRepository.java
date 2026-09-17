/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.domain;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ShareAccountYieldAccrualRepository extends JpaRepository<ShareAccountYieldAccrual, Long> {
    Optional<ShareAccountYieldAccrual> findBySourceReference(String sourceReference);
    boolean existsByShareAccountIdAndAccrualDate(Long shareAccountId, LocalDate accrualDate);
    List<ShareAccountYieldAccrual> findByShareAccountIdOrderByAccrualDateAscIdAsc(Long shareAccountId);

    @Query("select max(a.accrualDate) from ShareAccountYieldAccrual a where a.shareAccount.id = :accountId")
    LocalDate findLatestAccrualDate(@Param("accountId") Long accountId);

    @Query("select coalesce(sum(a.bookedAmount), 0) from ShareAccountYieldAccrual a where a.shareAccount.id = :accountId")
    BigDecimal sumBookedAmount(@Param("accountId") Long accountId);
}
