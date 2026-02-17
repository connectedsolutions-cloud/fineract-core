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
package org.apache.fineract.portfolio.comite.service;

import java.util.List;
import org.apache.fineract.portfolio.comite.data.ApprovedLoansDisbursementSumData;
import org.apache.fineract.portfolio.comite.data.SesionComiteData;
import org.apache.fineract.portfolio.loanaccount.data.LoanAccountData;

public interface SesionComiteReadPlatformService {

    List<SesionComiteData> retrieveAllSessions();

    SesionComiteData retrieveOneSession(Long sessionId);

    List<LoanAccountData> retrievePendingLoansForUser(Long currentOfficeId);

    /**
     * Returns the list of loan IDs unanimously approved for the given session. Session is loaded
     * with office scoping (caller supplies the comite-session's office_id).
     *
     * @param sessionId session id (from e.g. step references)
     * @param officeId  office id of the comite-session (for findByIdAndOfficeId)
     * @return list of approved loan IDs, or empty list if session not found or no approvals
     */
    List<Long> retrieveApprovedLoanIds(Long sessionId, Long officeId);

    /**
     * Returns the sum of net disbursal amounts for all loans unanimously approved in the given
     * session, plus currency info for display. Session is loaded with office scoping.
     *
     * @param sessionId session id (from e.g. step references)
     * @param officeId  office id of the comite-session (for findByIdAndOfficeId)
     * @return sum data (totalDisbursementAmount, currencyCode, currencyDigits), or null if session
     *         not found
     */
    ApprovedLoansDisbursementSumData retrieveApprovedLoansDisbursementSum(Long sessionId, Long officeId);
}
