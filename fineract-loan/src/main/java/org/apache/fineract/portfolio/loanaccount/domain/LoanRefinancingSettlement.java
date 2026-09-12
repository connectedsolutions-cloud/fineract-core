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

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.LocalDate;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

/**
 * One predecessor payoff funded by a successor refinancing loan.
 *
 * <p>
 * The parent is still persisted in {@code m_loan_topup} for backwards compatibility, but this collection is the
 * authoritative relationship for both single-loan refinancing and multi-loan consolidation.
 * </p>
 */
@Entity
@Table(name = "m_loan_refinancing_settlement")
public class LoanRefinancingSettlement extends AbstractPersistableCustom<Long> {

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "refinancing_id", nullable = false)
    private LoanTopupDetails refinancing;

    @Column(name = "closure_loan_id", nullable = false)
    private Long closureLoanId;

    @Column(name = "account_transfer_details_id")
    private Long accountTransferDetailsId;

    @Column(name = "repayment_transaction_id")
    private Long repaymentTransactionId;

    @Column(name = "settlement_amount", precision = 19, scale = 6)
    private BigDecimal settlementAmount;

    @Column(name = "settlement_type", nullable = false, length = 30)
    private String settlementType = "FULL_CLOSE";

    @Column(name = "principal_portion", precision = 19, scale = 6)
    private BigDecimal principalPortion;

    @Column(name = "interest_portion", precision = 19, scale = 6)
    private BigDecimal interestPortion;

    @Column(name = "fee_charges_portion", precision = 19, scale = 6)
    private BigDecimal feeChargesPortion;

    @Column(name = "penalty_charges_portion", precision = 19, scale = 6)
    private BigDecimal penaltyChargesPortion;

    @Column(name = "legacy_cross_client", nullable = false)
    private boolean legacyCrossClient;

    @Column(name = "authorization_basis", length = 50)
    private String authorizationBasis;

    @Column(name = "source_system", length = 30)
    private String sourceSystem;

    @Column(name = "source_liquidation_id", length = 100)
    private String sourceLiquidationId;

    @Column(name = "source_payoff_movement_id", length = 100)
    private String sourcePayoffMovementId;

    @Column(name = "source_operator_id", length = 100)
    private String sourceOperatorId;

    @Column(name = "source_payoff_date")
    private LocalDate sourcePayoffDate;

    @Column(name = "predecessor_client_id")
    private Long predecessorClientId;

    @Column(name = "successor_client_id")
    private Long successorClientId;

    protected LoanRefinancingSettlement() {}

    LoanRefinancingSettlement(final LoanTopupDetails refinancing, final Long closureLoanId) {
        this(refinancing, closureLoanId, "FULL_CLOSE");
    }

    LoanRefinancingSettlement(final LoanTopupDetails refinancing, final Long closureLoanId, final String settlementType) {
        this.refinancing = refinancing;
        this.closureLoanId = closureLoanId;
        this.settlementType = settlementType;
    }

    public Long getLoanIdToClose() {
        return closureLoanId;
    }

    public String getSettlementType() {
        return settlementType;
    }

    public void recordSettlement(final Long accountTransferDetailsId, final Long repaymentTransactionId, final BigDecimal settlementAmount,
            final SourceExactRepaymentAllocation allocation) {
        this.accountTransferDetailsId = accountTransferDetailsId;
        this.repaymentTransactionId = repaymentTransactionId;
        this.settlementAmount = settlementAmount;
        if (allocation != null) {
            this.principalPortion = allocation.principal();
            this.interestPortion = allocation.interest();
            this.feeChargesPortion = allocation.feeCharges();
            this.penaltyChargesPortion = allocation.penaltyCharges();
        }
    }

    public void recordLegacyCrossClientEvidence(final String authorizationBasis, final String sourceSystem,
            final String sourceLiquidationId, final String sourcePayoffMovementId, final String sourceOperatorId,
            final LocalDate sourcePayoffDate, final Long predecessorClientId, final Long successorClientId) {
        this.legacyCrossClient = true;
        this.authorizationBasis = authorizationBasis;
        this.sourceSystem = sourceSystem;
        this.sourceLiquidationId = sourceLiquidationId;
        this.sourcePayoffMovementId = sourcePayoffMovementId;
        this.sourceOperatorId = sourceOperatorId;
        this.sourcePayoffDate = sourcePayoffDate;
        this.predecessorClientId = predecessorClientId;
        this.successorClientId = successorClientId;
    }
}
