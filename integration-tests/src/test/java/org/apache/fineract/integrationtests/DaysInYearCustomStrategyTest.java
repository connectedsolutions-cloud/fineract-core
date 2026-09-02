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
package org.apache.fineract.integrationtests;

import java.io.IOException;
import java.math.BigDecimal;
import java.time.LocalDate;
import org.apache.fineract.client.models.GetLoanProductsProductIdResponse;
import org.apache.fineract.client.models.GetLoansLoanIdRepaymentPeriod;
import org.apache.fineract.client.models.GetLoansLoanIdResponse;
import org.apache.fineract.client.models.PostLoanProductsResponse;
import org.apache.fineract.client.models.PostLoansResponse;
import org.apache.fineract.client.models.PutLoanProductsProductIdRequest;
import org.apache.fineract.integrationtests.common.ClientHelper;
import org.apache.fineract.integrationtests.common.FineractClientHelper;
import org.apache.fineract.integrationtests.common.Utils;
import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;
import retrofit2.Call;
import retrofit2.Response;

public class DaysInYearCustomStrategyTest extends BaseLoanIntegrationTest {

    private final Long clientId = clientHelper.createClient(ClientHelper.defaultClientCreationRequest()).getResourceId();

    @Test
    public void test_HttpError_for_ValidationError_DaysInYearsCustomStrategy() {
        Call<PostLoanProductsResponse> loanProductCall = FineractClientHelper.getFineractClient().loanProducts
                .createLoanProduct(create4IProgressive()
                        // invalid settings combination
                        .daysInYearType(DaysInYearType.DAYS_360).daysInYearCustomStrategy(DaysInYearCustomStrategy.FEB_29_PERIOD_ONLY));
        try {
            Response<PostLoanProductsResponse> response = loanProductCall.execute();
            Assertions.assertEquals(403, response.code());
        } catch (IOException e) {
            Assertions.fail("Unexpected exception", e);
        }
    }

    @Test
    public void test_Update_DaysInYearsCustomStrategy_Value() {
        PostLoanProductsResponse postLoanProduct = loanProductHelper.createLoanProduct(create4IProgressive().currencyCode("USD")
                .daysInYearType(DaysInYearType.ACTUAL).daysInYearCustomStrategy(DaysInYearCustomStrategy.FEB_29_PERIOD_ONLY));
        Assertions.assertNotNull(postLoanProduct.getResourceId());
        final Long loanProductId = postLoanProduct.getResourceId();

        GetLoanProductsProductIdResponse loanProduct = loanTransactionHelper.getLoanProduct(loanProductId.intValue());
        Assertions.assertEquals("FEB_29_PERIOD_ONLY", loanProduct.getDaysInYearCustomStrategy().getId());

        loanProductHelper.updateLoanProductById(loanProductId,
                new PutLoanProductsProductIdRequest().daysInYearCustomStrategy(DaysInYearCustomStrategy.FULL_LEAP_YEAR));
        loanProduct = loanTransactionHelper.getLoanProduct(loanProductId.intValue());
        Assertions.assertEquals("FULL_LEAP_YEAR", loanProduct.getDaysInYearCustomStrategy().getId());
    }

    @Test
    public void testFEB_29_PERIOD_ONLY() {
        runAt("1 January 2024", () -> {
            PostLoanProductsResponse loanProduct = loanProductHelper.createLoanProduct(create4IProgressive().currencyCode("USD")
                    .daysInYearType(DaysInYearType.ACTUAL).daysInYearCustomStrategy(DaysInYearCustomStrategy.FEB_29_PERIOD_ONLY));
            Long loanId = applyAndApproveProgressiveLoan(clientId, loanProduct.getResourceId(), "1 January 2024", 10000.0, 99.99, 12, null);
            Assertions.assertNotNull(loanId);
            disburseLoan(loanId, BigDecimal.valueOf(10000), "1 January 2024");
            verifyRepaymentSchedule(loanId, //
                    installment(10000.0, null, "01 January 2024"), //
                    installment(519.92, 821.84, 1341.76, false, "01 February 2024"), //
                    installment(564.78, 776.98, 1341.76, false, "01 March 2024"), //
                    installment(609.07, 732.69, 1341.76, false, "01 April 2024"), //
                    installment(659.12, 682.64, 1341.76, false, "01 May 2024"), //
                    installment(713.29, 628.47, 1341.76, false, "01 June 2024"), //
                    installment(771.91, 569.85, 1341.76, false, "01 July 2024"), //
                    installment(835.35, 506.41, 1341.76, false, "01 August 2024"), //
                    installment(904.0, 437.76, 1341.76, false, "01 September 2024"), //
                    installment(978.3, 363.46, 1341.76, false, "01 October 2024"), //
                    installment(1058.7, 283.06, 1341.76, false, "01 November 2024"), //
                    installment(1145.71, 196.05, 1341.76, false, "01 December 2024"), //
                    installment(1239.85, 101.9, 1341.75, false, "01 January 2025") //
            );
        });
    }

    @Test
    public void testFULL_LEAP_YEAR() {
        runAt("1 January 2024", () -> {
            PostLoanProductsResponse loanProduct = loanProductHelper.createLoanProduct(create4IProgressive().currencyCode("USD")
                    .daysInYearType(DaysInYearType.ACTUAL).daysInYearCustomStrategy(DaysInYearCustomStrategy.FULL_LEAP_YEAR));
            Long loanId = applyAndApproveProgressiveLoan(clientId, loanProduct.getResourceId(), "1 January 2024", 10000.0, 99.99, 12, null);
            Assertions.assertNotNull(loanId);
            disburseLoan(loanId, BigDecimal.valueOf(10000), "1 January 2024");
            verifyRepaymentSchedule(loanId, //
                    installment(10000.0, null, "01 January 2024"), //
                    installment(521.04, 819.59, 1340.63, false, "01 February 2024"), //
                    installment(563.74, 776.89, 1340.63, false, "01 March 2024"), //
                    installment(609.95, 730.68, 1340.63, false, "01 April 2024"), //
                    installment(659.94, 680.69, 1340.63, false, "01 May 2024"), //
                    installment(714.03, 626.6, 1340.63, false, "01 June 2024"), //
                    installment(772.55, 568.08, 1340.63, false, "01 July 2024"), //
                    installment(835.86, 504.77, 1340.63, false, "01 August 2024"), //
                    installment(904.37, 436.26, 1340.63, false, "01 September 2024"), //
                    installment(978.49, 362.14, 1340.63, false, "01 October 2024"), //
                    installment(1058.69, 281.94, 1340.63, false, "01 November 2024"), //
                    installment(1145.46, 195.17, 1340.63, false, "01 December 2024"), //
                    installment(1235.88, 104.68, 1340.56, false, "01 January 2025") //
            );
        });
    }

    @Test
    public void testCumulativeActualUsesThePeriodStartYearThroughTheLoanLifecycle() {
        runAt("23 December 2027", () -> {
            PostLoanProductsResponse loanProduct = loanProductHelper.createLoanProduct(create4ICumulative().currencyCode("USD")
                    .numberOfRepayments(3).amortizationType(0).interestRatePerPeriod(84D).daysInMonthType(DaysInMonthType.ACTUAL)
                    .daysInYearType(DaysInYearType.ACTUAL).isInterestRecalculationEnabled(false));

            PostLoansResponse application = loanTransactionHelper.applyLoan(applyCumulativeLoanRequest(clientId,
                    loanProduct.getResourceId(), "23 December 2027", 392D, 84D, 3, request -> request.amortizationType(0)));
            Long loanId = application.getResourceId();

            assertCumulativeActualInterest(loanId);
            loanTransactionHelper.approveLoan(loanId, approveLoanRequest(392D, "23 December 2027"));
            assertCumulativeActualInterest(loanId);
            disburseLoan(loanId, BigDecimal.valueOf(392), "23 December 2027");
            assertCumulativeActualInterest(loanId);
        });
    }

    private void assertCumulativeActualInterest(final Long loanId) {
        GetLoansLoanIdResponse loan = loanTransactionHelper.getLoan(requestSpec, responseSpec, loanId.intValue());
        assertRepaymentPeriod(loan, 1, LocalDate.of(2027, 12, 23), LocalDate.of(2028, 1, 23), 27.97);
        assertRepaymentPeriod(loan, 2, LocalDate.of(2028, 1, 23), LocalDate.of(2028, 2, 23), 18.59);
        assertRepaymentPeriod(loan, 3, LocalDate.of(2028, 2, 23), LocalDate.of(2028, 3, 23), 8.70);
    }

    private void assertRepaymentPeriod(final GetLoansLoanIdResponse loan, final int periodNumber, final LocalDate expectedFromDate,
            final LocalDate expectedDueDate, final double expectedInterest) {
        GetLoansLoanIdRepaymentPeriod period = loan.getRepaymentSchedule().getPeriods().stream()
                .filter(candidate -> Integer.valueOf(periodNumber).equals(candidate.getPeriod())).findFirst().orElseThrow();
        Assertions.assertEquals(expectedFromDate, period.getFromDate());
        Assertions.assertEquals(expectedDueDate, period.getDueDate());
        Assertions.assertEquals(expectedInterest, Utils.getDoubleValue(period.getInterestDue()));
    }
}
