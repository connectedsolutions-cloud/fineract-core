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
package org.apache.fineract.portfolio.shareaccounts.domain;

import org.apache.fineract.infrastructure.security.datascope.DataScopeService;
import org.apache.fineract.portfolio.accounts.exceptions.ShareAccountNotFoundException;
import org.apache.fineract.portfolio.client.domain.Client;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class ShareAccountRepositoryWrapper {

    private final ShareAccountRepository shareAccountRepository;
    private final DataScopeService dataScopeService;

    @Autowired
    public ShareAccountRepositoryWrapper(final ShareAccountRepository shareAccountRepository, final DataScopeService dataScopeService) {
        this.shareAccountRepository = shareAccountRepository;
        this.dataScopeService = dataScopeService;
    }

    public ShareAccount findOneWithNotFoundDetection(final Long accountId) {
        final ShareAccount account = this.shareAccountRepository.findById(accountId)
                .orElseThrow(() -> new ShareAccountNotFoundException(accountId));
        final Client client = account.getClient();
        final Long officeId = client != null && client.getOffice() != null ? client.getOffice().getId() : null;
        final Long clientStaffId = client != null ? client.staffId() : null;
        final Long gestorId = client != null ? client.gestorId() : null;
        if (!this.dataScopeService.canAccessShare(officeId, clientStaffId, gestorId)) {
            throw new ShareAccountNotFoundException(accountId);
        }
        return account;
    }

    public void save(final ShareAccount shareAccount) {
        this.shareAccountRepository.save(shareAccount);
    }

    public void saveAndFlush(final ShareAccount shareAccount) {
        this.shareAccountRepository.saveAndFlush(shareAccount);
    }
}
