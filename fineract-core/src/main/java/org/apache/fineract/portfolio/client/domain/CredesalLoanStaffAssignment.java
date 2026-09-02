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
package org.apache.fineract.portfolio.client.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.io.Serial;
import java.io.Serializable;
import lombok.Getter;

/** Read-only mapping used to include loan-level staff assignments in client search. */
@Entity
@Table(name = "credesal_loan_staff_assignment")
@Getter
public class CredesalLoanStaffAssignment implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    @Id
    @Column(name = "loan_id")
    private Long loanId;

    @Column(name = "client_id")
    private Long clientId;

    @Column(name = "promoter_staff_id")
    private Long promoterStaffId;

    @Column(name = "account_executive_staff_id")
    private Long accountExecutiveStaffId;

    @Column(name = "collections_manager_staff_id")
    private Long collectionsManagerStaffId;

    protected CredesalLoanStaffAssignment() {}
}
