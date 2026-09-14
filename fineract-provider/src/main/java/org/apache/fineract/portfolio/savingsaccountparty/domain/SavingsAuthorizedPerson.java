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
package org.apache.fineract.portfolio.savingsaccountparty.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.LocalDate;
import java.time.LocalDateTime;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;
import org.apache.fineract.infrastructure.core.domain.AbstractPersistableCustom;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;

@Entity
@Table(name = "credesal_savings_authorized_person")
@Getter
@Setter
@NoArgsConstructor
public class SavingsAuthorizedPerson extends AbstractPersistableCustom<Long> {
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "savings_account_id", nullable = false)
    private SavingsAccount savingsAccount;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "linked_client_id")
    private Client linkedClient;
    @Column(name = "external_id", length = 100)
    private String externalId;
    @Column(name = "given_name", length = 50, nullable = false)
    private String givenName;
    @Column(name = "surname", length = 50)
    private String surname;
    @Column(name = "date_of_birth")
    private LocalDate dateOfBirth;
    @Column(name = "dui", length = 20)
    private String dui;
    @Column(name = "relationship", length = 50)
    private String relationship;
    @Column(name = "address", length = 254)
    private String address;
    @Column(name = "phone", length = 15)
    private String phone;
    @Column(name = "print_on_contract")
    private Boolean printOnContract;
    @Column(name = "print_on_passbook")
    private Boolean printOnPassbook;
    @Column(name = "signature_reference", length = 255)
    private String signatureReference;
    @Column(name = "source_hash", length = 64)
    private String sourceHash;
    @Column(name = "is_active", nullable = false)
    private boolean active = true;
    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
