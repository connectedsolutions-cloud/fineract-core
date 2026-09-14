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
package org.apache.fineract.portfolio.savingsaccountparty.data;

import java.math.BigDecimal;
import java.time.LocalDate;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsBeneficiary;

@Getter
@RequiredArgsConstructor
public class SavingsBeneficiaryData {
    private final Long id;
    private final Long savingsAccountId;
    private final Long linkedClientId;
    private final String externalId;
    private final String givenName;
    private final String surname;
    private final BigDecimal allocationPercentage;
    private final LocalDate dateOfBirth;
    private final String sourceAge;
    private final String dui;
    private final String relationship;
    private final String address;
    private final String phone;
    private final Boolean communicateDesignation;

    public static SavingsBeneficiaryData from(final SavingsBeneficiary beneficiary) {
        return new SavingsBeneficiaryData(beneficiary.getId(), beneficiary.getSavingsAccount().getId(),
                beneficiary.getLinkedClient() == null ? null : beneficiary.getLinkedClient().getId(), beneficiary.getExternalId(),
                beneficiary.getGivenName(), beneficiary.getSurname(), beneficiary.getAllocationPercentage(), beneficiary.getDateOfBirth(),
                beneficiary.getSourceAge(), beneficiary.getDui(), beneficiary.getRelationship(), beneficiary.getAddress(), beneficiary.getPhone(),
                beneficiary.getCommunicateDesignation());
    }
}
