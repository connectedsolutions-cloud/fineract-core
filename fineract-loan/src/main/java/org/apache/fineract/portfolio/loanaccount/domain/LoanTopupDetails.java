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

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.OneToMany;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_loan_topup")
public class LoanTopupDetails extends AbstractPersistableCustom<Long> {

    @OneToOne
    @JoinColumn(name = "loan_id", nullable = false)
    private Loan loan;

    @Column(name = "closure_loan_id", nullable = false)
    private Long closureLoanId;

    @Column(name = "account_transfer_details_id", nullable = true)
    private Long accountTransferDetailsId;

    @Column(name = "topup_amount", nullable = true)
    private BigDecimal topupAmount;

    @Column(name = "operation_type", nullable = false)
    private String operationType = "SINGLE_REFINANCE";

    @OneToMany(mappedBy = "refinancing", cascade = CascadeType.ALL, orphanRemoval = true, fetch = FetchType.LAZY)
    private List<LoanRefinancingSettlement> settlements = new ArrayList<>();

    protected LoanTopupDetails() {}

    public LoanTopupDetails(final Loan loan, final Long loanIdToClose) {
        this(loan, List.of(loanIdToClose));
    }

    public LoanTopupDetails(final Loan loan, final Collection<Long> loanIdsToClose) {
        if (loanIdsToClose == null || loanIdsToClose.isEmpty()) {
            throw new IllegalArgumentException("A refinancing must contain at least one predecessor loan");
        }
        this.loan = loan;
        final List<Long> orderedIds = loanIdsToClose.stream().distinct().sorted().toList();
        if (orderedIds.size() != loanIdsToClose.size()) {
            throw new IllegalArgumentException("A predecessor loan cannot appear more than once in a refinancing");
        }
        this.closureLoanId = orderedIds.get(0);
        this.operationType = orderedIds.size() == 1 ? "SINGLE_REFINANCE" : "CONSOLIDATION";
        orderedIds.forEach(id -> this.settlements.add(new LoanRefinancingSettlement(this, id)));
    }

    public Long getLoanIdToClose() {
        return this.closureLoanId;
    }

    public List<Long> getLoanIdsToClose() {
        if (settlements == null || settlements.isEmpty()) {
            return List.of(closureLoanId);
        }
        return settlements.stream().map(LoanRefinancingSettlement::getLoanIdToClose).sorted().toList();
    }

    public List<LoanRefinancingSettlement> getSettlements() {
        if ((settlements == null || settlements.isEmpty()) && closureLoanId != null) {
            settlements = new ArrayList<>(List.of(new LoanRefinancingSettlement(this, closureLoanId)));
        }
        settlements.sort(Comparator.comparing(LoanRefinancingSettlement::getLoanIdToClose));
        return settlements;
    }

    public boolean isConsolidation() {
        return getLoanIdsToClose().size() > 1;
    }

    public String getOperationType() {
        return operationType;
    }

    public BigDecimal getTopupAmount() {
        return this.topupAmount;
    }

    public void setTopupAmount(BigDecimal topupAmount) {
        this.topupAmount = topupAmount;
    }

    public void setAccountTransferDetails(Long accountTransferDetailsId) {
        this.accountTransferDetailsId = accountTransferDetailsId;
    }

}
