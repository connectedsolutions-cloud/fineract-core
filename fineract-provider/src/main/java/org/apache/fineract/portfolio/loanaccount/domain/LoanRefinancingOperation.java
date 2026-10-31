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

import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.HashSet;
import java.util.Set;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;

@Entity
@Table(name = "m_loan_refinancing_operation")
@Getter
@Setter
@NoArgsConstructor
public class LoanRefinancingOperation extends AbstractPersistableCustom<Long> {

    @Version
    private Long version;
    @Column(name = "loan_id", nullable = false)
    private Long loanId;
    @Column(name = "office_id", nullable = false)
    private Long officeId;
    @Column(name = "operation_date", nullable = false)
    private LocalDate operationDate;
    @Column(name = "currency_code", nullable = false)
    private String currencyCode;
    @Column(name = "proceeds_mode", nullable = false)
    private String proceedsMode;
    @Column(name = "payout_entitlement", nullable = false)
    private BigDecimal payoutEntitlement = BigDecimal.ZERO;
    @Column(name = "delivered_amount", nullable = false)
    private BigDecimal deliveredAmount = BigDecimal.ZERO;
    @Column(name = "returned_amount", nullable = false)
    private BigDecimal returnedAmount = BigDecimal.ZERO;
    @Column(name = "voucher_id")
    private Long voucherId;
    @Column(name = "reversed", nullable = false)
    private boolean reversed;
    @Column(name = "reversal_date")
    private LocalDate reversalDate;
    @Column(name = "legacy", nullable = false)
    private boolean legacy;
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "m_loan_refinancing_operation_transaction", joinColumns = @JoinColumn(name = "operation_id"))
    @Column(name = "transaction_id")
    private Set<Long> transactionIds = new HashSet<>();
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "m_loan_refinancing_operation_journal", joinColumns = @JoinColumn(name = "operation_id"))
    @Column(name = "journal_entry_id")
    private Set<Long> journalEntryIds = new HashSet<>();

    public BigDecimal outstandingCash() {
        return deliveredAmount.subtract(returnedAmount);
    }

    public BigDecimal undelivered() {
        return payoutEntitlement.subtract(deliveredAmount);
    }
}
