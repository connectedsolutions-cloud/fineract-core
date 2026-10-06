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
package org.apache.fineract.portfolio.loanaccount.service;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.google.gson.JsonArray;
import com.google.gson.JsonParser;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.organisation.monetary.domain.Money;
import org.apache.fineract.organisation.monetary.domain.MonetaryCurrency;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.junit.jupiter.api.Test;

class SourceExactHistoricalRefinancingTargetGuardTest {

    private static final LocalDate PAYOFF_DATE = LocalDate.of(2026, 8, 7);

    @Test
    void acceptsOnlyTheFrozenNativeLaterTransaction() {
        Loan loan = loanWithLaterTransaction("ARISSTO:CRD-MOV:later", "5.00");

        assertThatCode(() -> LoanWritePlatformServiceJpaRepositoryImpl.assertHistoricalRefinancingTarget(expected("5.00"),
                List.of(loan), PAYOFF_DATE, Set.of())).doesNotThrowAnyException();
    }

    @Test
    void rejectsTargetAmountChangedAfterPlanning() {
        Loan loan = loanWithLaterTransaction("ARISSTO:CRD-MOV:later", "6.00");

        assertThatThrownBy(() -> LoanWritePlatformServiceJpaRepositoryImpl.assertHistoricalRefinancingTarget(expected("5.00"),
                List.of(loan), PAYOFF_DATE, Set.of())).isInstanceOf(GeneralPlatformDomainRuleException.class);
    }

    @Test
    void rejectsUnownedLaterActivityEvenWhenItsAmountMatches() {
        Loan loan = loanWithLaterTransaction("native-payment", "5.00");

        assertThatThrownBy(() -> LoanWritePlatformServiceJpaRepositoryImpl.assertHistoricalRefinancingTarget(expected("5.00"),
                List.of(loan), PAYOFF_DATE, Set.of())).isInstanceOf(GeneralPlatformDomainRuleException.class);
    }

    private static Loan loanWithLaterTransaction(final String externalId, final String amount) {
        Loan loan = mock(Loan.class);
        LoanTransaction transaction = mock(LoanTransaction.class);
        MonetaryCurrency currency = mock(MonetaryCurrency.class);
        when(loan.getId()).thenReturn(22L);
        when(loan.getExternalId()).thenReturn(new ExternalId("ARISSTO:CRD:22"));
        when(loan.isOpen()).thenReturn(true);
        when(loan.getCurrency()).thenReturn(currency);
        when(loan.getLoanTransactions()).thenReturn(List.of(transaction));
        when(loan.isUserTransaction(transaction)).thenReturn(true);
        when(transaction.getExternalId()).thenReturn(new ExternalId(externalId));
        when(transaction.getTransactionDate()).thenReturn(LocalDate.of(2026, 9, 21));
        Money amountMoney = money(amount);
        Money principalMoney = money(amount);
        Money interestMoney = money("0");
        Money feeMoney = money("0");
        Money penaltyMoney = money("0");
        when(transaction.getAmount(currency)).thenReturn(amountMoney);
        when(transaction.getPrincipalPortion(currency)).thenReturn(principalMoney);
        when(transaction.getInterestPortion(currency)).thenReturn(interestMoney);
        when(transaction.getFeeChargesPortion(currency)).thenReturn(feeMoney);
        when(transaction.getPenaltyChargesPortion(currency)).thenReturn(penaltyMoney);
        return loan;
    }

    private static Money money(final String amount) {
        Money value = mock(Money.class);
        when(value.getAmount()).thenReturn(new BigDecimal(amount));
        return value;
    }

    private static JsonArray expected(final String amount) {
        return JsonParser.parseString("[{\"loanId\":22,\"externalId\":\"ARISSTO:CRD-MOV:later\","
                + "\"date\":\"2026-09-21\",\"amount\":\"" + amount + "\",\"principal\":\"" + amount
                + "\",\"interest\":\"0\",\"fee\":\"0\",\"penalty\":\"0\"}]").getAsJsonArray();
    }
}
