/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
package org.apache.fineract.portfolio.loanaccount.domain;

import java.util.List;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface LoanRefinancingOperationRepository extends JpaRepository<LoanRefinancingOperation, Long> {

    Optional<LoanRefinancingOperation> findFirstByLoanIdOrderByIdDesc(Long loanId);

    @Query("select count(o) from LoanRefinancingOperation o join o.transactionIds t where o.reversed=false and t=:transactionId")
    long countActiveOwners(@org.springframework.data.repository.query.Param("transactionId") Long transactionId);

    @Query("select o from LoanRefinancingOperation o where o.reversed=false and o.proceedsMode='CASH' and o.returnedAmount=0 and o.payoutEntitlement>o.deliveredAmount order by o.id")
    List<LoanRefinancingOperation> findPendingCash();
}
