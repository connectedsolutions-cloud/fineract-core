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
package org.apache.fineract.portfolio.collateralmanagement.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.math.BigDecimal;
import java.util.List;
import org.apache.fineract.portfolio.client.domain.Client;
import org.apache.fineract.portfolio.client.domain.ClientRepositoryWrapper;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProductRepository;
import org.junit.jupiter.api.Test;

class ClientCollateralManagementRepositoryWrapperTest {

    @Test
    void returnsAllClientCollateralsWhenNoLoanProductFilterIsSupplied() {
        ClientCollateralManagementRepository repository = mock(ClientCollateralManagementRepository.class);
        ClientRepositoryWrapper clientRepository = mock(ClientRepositoryWrapper.class);
        Client client = mock(Client.class);
        ClientCollateralManagement clientCollateral = mock(ClientCollateralManagement.class);
        CollateralManagementDomain collateral = mock(CollateralManagementDomain.class);
        when(clientRepository.findOneWithNotFoundDetection(7L)).thenReturn(client);
        when(repository.findByClientId(client)).thenReturn(List.of(clientCollateral));
        when(clientCollateral.getId()).thenReturn(11L);
        when(clientCollateral.getQuantity()).thenReturn(BigDecimal.ONE);
        when(clientCollateral.getTotal()).thenReturn(new BigDecimal("12000.00"));
        when(clientCollateral.getTotalCollateral(new BigDecimal("12000.00"))).thenReturn(new BigDecimal("12000.00"));
        when(clientCollateral.getCollaterals()).thenReturn(collateral);
        when(collateral.getName()).thenReturn("ARISSTO-COLLATERAL");
        ClientCollateralManagementRepositoryWrapper wrapper = new ClientCollateralManagementRepositoryWrapper(repository, clientRepository,
                mock(LoanProductRepository.class));

        var result = wrapper.getClientCollateralData(7L, null);

        assertEquals(1, result.size());
        assertEquals(11L, result.getFirst().getId());
    }
}
