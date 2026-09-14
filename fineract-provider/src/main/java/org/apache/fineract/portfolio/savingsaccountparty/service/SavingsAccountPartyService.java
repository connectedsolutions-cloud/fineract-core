/**
 * Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information regarding copyright ownership. The ASF licenses this file to you under
 * the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain
 * a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS"
 * BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language
 * governing permissions and limitations under the License.
 */
package org.apache.fineract.portfolio.savingsaccountparty.service;

import java.util.List;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsAuthorizedPersonRequest;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryData;
import org.apache.fineract.portfolio.savingsaccountparty.data.SavingsBeneficiaryRequest;

public interface SavingsAccountPartyService {
    List<SavingsBeneficiaryData> retrieveBeneficiaries(Long accountId);
    List<SavingsBeneficiaryData> replaceBeneficiaries(Long accountId, List<SavingsBeneficiaryRequest> requests);
    List<SavingsAuthorizedPersonData> retrieveAuthorizedPersons(Long accountId);
    List<SavingsAuthorizedPersonData> replaceAuthorizedPersons(Long accountId, List<SavingsAuthorizedPersonRequest> requests);
    SavingsAuthorizedPersonData createAuthorizedPerson(Long accountId, SavingsAuthorizedPersonRequest request);
    SavingsAuthorizedPersonData updateAuthorizedPerson(Long accountId, Long personId, SavingsAuthorizedPersonRequest request);
    void deleteAuthorizedPerson(Long accountId, Long personId);
}
