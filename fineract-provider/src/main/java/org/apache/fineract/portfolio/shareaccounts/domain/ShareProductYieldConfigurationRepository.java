/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ShareProductYieldConfigurationRepository extends JpaRepository<ShareProductYieldConfiguration, Long> {
    List<ShareProductYieldConfiguration> findByEnabledTrue();
}
