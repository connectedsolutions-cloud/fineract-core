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

import java.time.LocalDate;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.loanaccount.exception.LoanNotFoundException;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class LoanSimulationValidator {

    private final LoanRepository loanRepository;

    /**
     * Validates that simulated_date can only move forward (not backward).
     *
     * @param loan
     *            the loan to validate
     * @param newDate
     *            the new simulated date to validate
     * @throws IllegalArgumentException
     *             if the new date is before the current simulated date
     */
    public void validateSimulatedDateForwardOnly(Loan loan, LocalDate newDate) {
        if (newDate != null && loan.getSimulatedDate() != null && DateUtils.isBefore(newDate, loan.getSimulatedDate())) {
            throw new IllegalArgumentException(
                    "Simulated date can only move forward. Current: " + loan.getSimulatedDate() + ", New: " + newDate);
        }
    }

    /**
     * Validates that simulated_date cannot be in the past relative to loan disbursement date.
     *
     * @param loan
     *            the loan to validate
     * @param newDate
     *            the new simulated date to validate
     * @throws IllegalArgumentException
     *             if the new date is before the disbursement date
     */
    public void validateSimulatedDateNotBeforeDisbursement(Loan loan, LocalDate newDate) {
        if (newDate != null && loan.getActualDisbursementDate() != null && DateUtils.isBefore(newDate, loan.getActualDisbursementDate())) {
            throw new IllegalArgumentException("Simulated date cannot be before disbursement date. Disbursement: "
                    + loan.getActualDisbursementDate() + ", New: " + newDate);
        }
    }

    /**
     * Validates that when is_simulation = false, simulated_date must be cleared.
     *
     * @param isSimulation
     *            the new is_simulation value
     * @param simulatedDate
     *            the simulated_date value
     * @throws IllegalArgumentException
     *             if is_simulation is false but simulated_date is not null
     */
    public void validateSimulatedDateClearedWhenDisabled(Boolean isSimulation, LocalDate simulatedDate) {
        if (Boolean.FALSE.equals(isSimulation) && simulatedDate != null) {
            throw new IllegalArgumentException("Simulated date must be cleared when simulation is disabled.");
        }
    }

    /**
     * Validates that simulation mode can only be enabled for active loans.
     *
     * @param loan
     *            the loan to validate
     * @throws IllegalArgumentException
     *             if the loan is closed, cancelled, or written off
     */
    public void validateSimulationOnlyForActiveLoans(Loan loan) {
        if (loan.isClosed() || loan.isCancelled() || loan.isClosedWrittenOff()) {
            throw new IllegalArgumentException("Simulation mode can only be enabled for active loans. Loan status: " + loan.getStatus());
        }
    }

    /**
     * Validates all simulation-related business rules.
     *
     * @param loanId
     *            the loan ID
     * @param isSimulation
     *            the new is_simulation value
     * @param simulatedDate
     *            the new simulated_date value
     */
    public void validateSimulationFields(Long loanId, Boolean isSimulation, LocalDate simulatedDate) {
        final Loan loan = this.loanRepository.findById(loanId).orElseThrow(() -> new LoanNotFoundException(loanId));

        if (Boolean.TRUE.equals(isSimulation)) {
            validateSimulationOnlyForActiveLoans(loan);
            if (simulatedDate != null) {
                validateSimulatedDateForwardOnly(loan, simulatedDate);
                validateSimulatedDateNotBeforeDisbursement(loan, simulatedDate);
            }
        } else {
            validateSimulatedDateClearedWhenDisabled(isSimulation, simulatedDate);
        }
    }
}
