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

import java.time.LocalDate;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.portfolio.savingsaccountparty.domain.SavingsAuthorizedPerson;

@Getter
@RequiredArgsConstructor
public class SavingsAuthorizedPersonData {
    private final Long id;
    private final Long savingsAccountId;
    private final Long linkedClientId;
    private final String externalId;
    private final String givenName;
    private final String surname;
    private final LocalDate dateOfBirth;
    private final String dui;
    private final String relationship;
    private final String address;
    private final String phone;
    private final Boolean printOnContract;
    private final Boolean printOnPassbook;
    private final String signatureReference;

    public static SavingsAuthorizedPersonData from(final SavingsAuthorizedPerson person) {
        return new SavingsAuthorizedPersonData(person.getId(), person.getSavingsAccount().getId(),
                person.getLinkedClient() == null ? null : person.getLinkedClient().getId(), person.getExternalId(), person.getGivenName(),
                person.getSurname(), person.getDateOfBirth(), person.getDui(), person.getRelationship(), person.getAddress(), person.getPhone(),
                person.getPrintOnContract(), person.getPrintOnPassbook(), person.getSignatureReference());
    }
}
