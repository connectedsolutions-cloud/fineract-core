/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.domain;

import jakarta.persistence.LockModeType;
import java.math.BigDecimal;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface ShareAccountYieldSettlementRepository extends JpaRepository<ShareAccountYieldSettlement, Long> {

    Optional<ShareAccountYieldSettlement> findByReference(String reference);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select a from ShareAccount a where a.id = :accountId")
    Optional<ShareAccount> lockShareAccount(@Param("accountId") Long accountId);

    @Query("select coalesce(sum(s.amount), 0) from ShareAccountYieldSettlement s where s.shareAccount.id = :accountId")
    BigDecimal sumSettledAmount(@Param("accountId") Long accountId);
}
