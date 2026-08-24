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
import org.apache.fineract.infrastructure.event.business.domain.loan.LoanChargebackTransactionBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.loan.product.LoanProductCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.loan.transaction.LoanTransactionMakeRepaymentPostBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.savings.SavingsPostInterestBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.savings.transaction.SavingsDepositBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.share.ShareAccountApproveBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.share.ShareAccountCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.share.ShareProductDividentsCreateBusinessEvent;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTransaction;
import org.apache.fineract.portfolio.loanproduct.domain.LoanProduct;
import org.apache.fineract.portfolio.savings.domain.SavingsAccount;
import org.apache.fineract.portfolio.savings.domain.SavingsAccountTransaction;
import org.apache.fineract.portfolio.shareaccounts.domain.ShareAccount;

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
        businessEventNotifierService.addPostBusinessEventListener(SavingsDepositBusinessEvent.class, new SavingsAccountDepositListener());
        businessEventNotifierService.addPostBusinessEventListener(ShareProductDividentsCreateBusinessEvent.class,
                new ShareProductDividendCreatedListener());
        businessEventNotifierService.addPostBusinessEventListener(SavingsPostInterestBusinessEvent.class,
                new SavingsPostInterestListener());
        businessEventNotifierService.addPostBusinessEventListener(LoanChargebackTransactionBusinessEvent.class,
                new LoanChargebackTransactionListener());
        businessEventNotifierService.addPostBusinessEventListener(LoanTransactionMakeRepaymentPostBusinessEvent.class,
                new LoanMakeRepaymentListener());
        businessEventNotifierService.addPostBusinessEventListener(LoanProductCreateBusinessEvent.class, new LoanProductCreatedListener());
        businessEventNotifierService.addPostBusinessEventListener(ShareAccountCreateBusinessEvent.class, new ShareAccountCreatedListener());
        businessEventNotifierService.addPostBusinessEventListener(ShareAccountApproveBusinessEvent.class,
                new ShareAccountApprovedListener());
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

    private final class SavingsAccountDepositListener implements BusinessEventListener<SavingsDepositBusinessEvent> {

        @Override
        public void onBusinessEvent(SavingsDepositBusinessEvent event) {
            SavingsAccountTransaction savingsAccountTransaction = event.get();
            buildNotification("READ_SAVINGSACCOUNT", "savingsAccount", savingsAccountTransaction.getSavingsAccount().getId(),
                    "Deposit made", "depositMade", context.authenticatedUser().getId(),
                    savingsAccountTransaction.getSavingsAccount().officeId());
        }
    }

    private final class ShareProductDividendCreatedListener implements BusinessEventListener<ShareProductDividentsCreateBusinessEvent> {

        @Override
        public void onBusinessEvent(ShareProductDividentsCreateBusinessEvent event) {
            Long shareProductId = event.get();
            buildNotification("READ_DIVIDEND_SHAREPRODUCT", "shareProduct", shareProductId, "Dividend posted to account", "dividendPosted",
                    context.authenticatedUser().getId(), context.authenticatedUser().getOffice().getId());
        }
    }

    private final class SavingsPostInterestListener implements BusinessEventListener<SavingsPostInterestBusinessEvent> {

        @Override
        public void onBusinessEvent(SavingsPostInterestBusinessEvent event) {
            SavingsAccount savingsAccount = event.get();
            buildNotification("READ_SAVINGSACCOUNT", "savingsAccount", savingsAccount.getId(), "Interest posted to account",
                    "interestPosted", context.authenticatedUser().getId(), savingsAccount.officeId());
        }
    }

    private final class LoanChargebackTransactionListener implements BusinessEventListener<LoanChargebackTransactionBusinessEvent> {

        @Override
        public void onBusinessEvent(LoanChargebackTransactionBusinessEvent event) {
            LoanTransaction loanTransaction = event.get();
            buildNotification(LoanChargebackTransactionBusinessEvent.LOAN_CHARGEBACK_TRANSACTION_PERMISSION,
                    LoanChargebackTransactionBusinessEvent.LOAN_CHARGEBACK_TRANSACTION_OBJECT_TYPE, loanTransaction.getId(),
                    LoanChargebackTransactionBusinessEvent.LOAN_CHARGEBACK_TRANSACTION_NOTIFICATION,
                    LoanChargebackTransactionBusinessEvent.LOAN_CHARGEBACK_TRANSACTION_EVENT_TYPE, context.authenticatedUser().getId(),
                    loanTransaction.getLoan().getOfficeId());
        }
    }

    private final class LoanMakeRepaymentListener implements BusinessEventListener<LoanTransactionMakeRepaymentPostBusinessEvent> {

        @Override
        public void onBusinessEvent(LoanTransactionMakeRepaymentPostBusinessEvent event) {
            Loan loan = event.get().getLoan();
            buildNotification("READ_LOAN", "loan", loan.getId(), "Repayment made", "repaymentMade", context.authenticatedUser().getId(),
                    loan.getOfficeId());
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

    private final class ShareAccountCreatedListener implements BusinessEventListener<ShareAccountCreateBusinessEvent> {

        @Override
        public void onBusinessEvent(ShareAccountCreateBusinessEvent event) {
            ShareAccount shareAccount = event.get();
            buildNotification("APPROVE_SHAREACCOUNT", "shareAccount", shareAccount.getId(), "New share account created", "created",
                    context.authenticatedUser().getId(), shareAccount.getOfficeId());
        }
    }

    private final class ShareAccountApprovedListener implements BusinessEventListener<ShareAccountApproveBusinessEvent> {

        @Override
        public void onBusinessEvent(ShareAccountApproveBusinessEvent event) {
            ShareAccount shareAccount = event.get();
            buildNotification("ACTIVATE_SHAREACCOUNT", "shareAccount", shareAccount.getId(), "Share account approved", "approved",
                    context.authenticatedUser().getId(), shareAccount.getOfficeId());
        }
    }

    private void buildNotification(String permission, String objectType, Long objectIdentifier, String notificationContent,
            String eventType, Long appUserId, Long officeId) {

        userNotificationService.notifyUsers(permission, objectType, objectIdentifier, notificationContent, eventType, appUserId, officeId);
    }

}
