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
package org.apache.fineract.notification.service;

import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.event.business.BusinessEventListener;
import org.apache.fineract.infrastructure.event.business.domain.group.CentersCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.group.GroupsCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.loan.product.LoanProductCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;

@RequiredArgsConstructor
@Slf4j
public class NotificationDomainServiceImpl implements NotificationDomainService {

    private final BusinessEventNotifierService businessEventNotifierService;
    private final PlatformSecurityContext context;
    private final UserNotificationService userNotificationService;

    @PostConstruct
    public void addListeners() {
        businessEventNotifierService.addPostBusinessEventListener(CentersCreateBusinessEvent.class, new CenterCreatedListener());
        businessEventNotifierService.addPostBusinessEventListener(GroupsCreateBusinessEvent.class, new GroupCreatedListener());
        businessEventNotifierService.addPostBusinessEventListener(LoanProductCreateBusinessEvent.class, new LoanProductCreatedListener());
    }

    private final class CenterCreatedListener implements BusinessEventListener<CentersCreateBusinessEvent> {

        @Override
        public void onBusinessEvent(CentersCreateBusinessEvent event) {
            CommandProcessingResult commandProcessingResult = event.get();
            buildNotification("ACTIVATE_CENTER", "center", commandProcessingResult.getGroupId(), "New center created", "created",
                    context.authenticatedUser().getId(), commandProcessingResult.getOfficeId());
        }
    }

    private final class GroupCreatedListener implements BusinessEventListener<GroupsCreateBusinessEvent> {

        @Override
        public void onBusinessEvent(GroupsCreateBusinessEvent event) {
            CommandProcessingResult commandProcessingResult = event.get();
            buildNotification("ACTIVATE_GROUP", "group", commandProcessingResult.getGroupId(), "New group created", "created",
                    context.authenticatedUser().getId(), commandProcessingResult.getOfficeId());
        }
    }

    private final class LoanProductCreatedListener implements BusinessEventListener<LoanProductCreateBusinessEvent> {

        @Override
        public void onBusinessEvent(LoanProductCreateBusinessEvent event) {
            LoanProduct loanProduct = event.get();
            buildNotification("READ_LOANPRODUCT", "loanProduct", loanProduct.getId(), "New loan product created", "created",
                    context.authenticatedUser().getId(), context.authenticatedUser().getOffice().getId());
        }
    }

    private void buildNotification(String permission, String objectType, Long objectIdentifier, String notificationContent,
            String eventType, Long appUserId, Long officeId) {

        userNotificationService.notifyUsers(permission, objectType, objectIdentifier, notificationContent, eventType, appUserId, officeId);
    }

}
