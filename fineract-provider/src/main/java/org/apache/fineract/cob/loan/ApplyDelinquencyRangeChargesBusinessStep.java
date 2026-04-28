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
package org.apache.fineract.cob.loan;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.service.LoanChargeWritePlatformService;
import org.springframework.stereotype.Component;

/**
 * Applies or recalculates loan charges tied to delinquency classification (after
 * {@link SetLoanDelinquencyTagsBusinessStep} in COB order).
 */
@Component
@RequiredArgsConstructor
public class ApplyDelinquencyRangeChargesBusinessStep implements LoanCOBBusinessStep {

    private final LoanChargeWritePlatformService loanChargeWritePlatformService;

    @Override
    public Loan execute(Loan loan) {
        loanChargeWritePlatformService.applyDelinquencyRangeChargesForLoan(loan.getId());
        return loan;
    }

    @Override
    public String getEnumStyledName() {
        return "APPLY_DELINQUENCY_RANGE_CHARGES";
    }

    @Override
    public String getHumanReadableName() {
        return "Apply delinquency range charges";
    }
}
