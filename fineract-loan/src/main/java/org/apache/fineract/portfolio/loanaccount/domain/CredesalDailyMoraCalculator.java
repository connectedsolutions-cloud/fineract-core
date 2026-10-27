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
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.fineract.portfolio.loanaccount.domain;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.List;

/**
 * The plan-type-1 branch of Arissto's FN_OBT_SALDO_MORA_CALC. The monthly percentage
 * is divided by 30; each eligible installment is rounded before summation.
 * This calculator deliberately does not post a charge or determine the loan's
 * migration accounting boundary.
 */
public final class CredesalDailyMoraCalculator {

    public record Installment(LocalDate dueDate, BigDecimal balanceBefore, BigDecimal balanceAfter) {}

    public BigDecimal calculate(final LocalDate operationDate, final BigDecimal outstandingPrincipal,
            final BigDecimal overduePrincipal, final int daysInArrears, final int graceDays, final LocalDate lastMoraPaymentDate,
            final BigDecimal monthlyRatePercent, final List<Installment> installments, final int currencyScale) {
        return calculate(operationDate, outstandingPrincipal, overduePrincipal, daysInArrears, graceDays,
                lastMoraPaymentDate, monthlyRatePercent, installments, currencyScale, List.of());
    }

    public BigDecimal calculate(final LocalDate operationDate, final BigDecimal outstandingPrincipal,
            final BigDecimal overduePrincipal, final int daysInArrears, final int graceDays, final LocalDate lastMoraPaymentDate,
            final BigDecimal monthlyRatePercent, final List<Installment> installments, final int currencyScale,
            final List<CredesalInterestPausePeriods.Period> frozenPeriods) {
        final BigDecimal zero = BigDecimal.ZERO.setScale(currencyScale);
        if (daysInArrears <= 0 || daysInArrears <= graceDays || overduePrincipal == null
                || overduePrincipal.signum() <= 0 || outstandingPrincipal == null || outstandingPrincipal.signum() <= 0
                || monthlyRatePercent == null || monthlyRatePercent.signum() <= 0) {
            return zero;
        }
        BigDecimal total = zero;
        for (Installment installment : installments) {
            if (installment.dueDate() == null || installment.dueDate().isAfter(operationDate)
                    || installment.balanceAfter().compareTo(outstandingPrincipal) >= 0) {
                continue;
            }
            final LocalDate accrualStart = lastMoraPaymentDate != null && lastMoraPaymentDate.isAfter(installment.dueDate())
                    ? lastMoraPaymentDate : installment.dueDate();
            final long days = CredesalInterestPausePeriods.chargeableDays(accrualStart, operationDate, frozenPeriods);
            if (days <= 0) {
                continue;
            }
            final BigDecimal base = (installment.balanceBefore().compareTo(outstandingPrincipal) < 0
                    ? installment.balanceBefore() : outstandingPrincipal).subtract(installment.balanceAfter());
            if (base.signum() <= 0) {
                continue;
            }
            final BigDecimal installmentMora = base.multiply(BigDecimal.valueOf(days)).multiply(monthlyRatePercent)
                    .divide(BigDecimal.valueOf(3000), currencyScale, RoundingMode.HALF_UP);
            total = total.add(installmentMora);
        }
        return total;
    }
}
