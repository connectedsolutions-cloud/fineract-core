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
package org.apache.fineract.infrastructure.core.service;

import org.apache.fineract.infrastructure.configuration.data.ResendCredentialsData;
import org.apache.fineract.infrastructure.configuration.data.SMTPCredentialsData;
import org.apache.fineract.infrastructure.configuration.service.ExternalServicesPropertiesReadPlatformService;
import org.apache.fineract.infrastructure.core.domain.EmailDetail;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.stereotype.Service;

@Service
public class GmailBackedPlatformEmailService implements PlatformEmailService {

    private final ExternalServicesPropertiesReadPlatformService externalServicesReadPlatformService;
    private final SmtpMailSenderFactory smtpMailSenderFactory;
    private final ResendEmailClient resendEmailClient;

    @Autowired
    public GmailBackedPlatformEmailService(final ExternalServicesPropertiesReadPlatformService externalServicesReadPlatformService,
            final SmtpMailSenderFactory smtpMailSenderFactory, final ResendEmailClient resendEmailClient) {
        this.externalServicesReadPlatformService = externalServicesReadPlatformService;
        this.smtpMailSenderFactory = smtpMailSenderFactory;
        this.resendEmailClient = resendEmailClient;
    }

    @Override
    public void sendToUserAccount(String organisationName, String contactName, String address, String username, String unencodedPassword) {

        final String subject = "Welcome " + contactName + " to " + organisationName;
        final String body = "You are receiving this email as your email account: " + address
                + " has being used to create a user account for an organisation named [" + organisationName + "] on Mifos.\n"
                + "You can login using the following credentials:\nusername: " + username + "\n" + "password: " + unencodedPassword + "\n"
                + "You must change this password upon first log in using Uppercase, Lowercase, number and character.\n"
                + "Thank you and welcome to the organisation.";

        final EmailDetail emailDetail = new EmailDetail(subject, body, address, contactName);
        sendDefinedEmail(emailDetail);

    }

    @Override
    public void sendDefinedEmail(EmailDetail emailDetails) {
        final ResendCredentialsData resendCredentials = this.externalServicesReadPlatformService.getResendCredentials();
        if (resendCredentials != null && resendCredentials.isConfigured()) {
            this.resendEmailClient.send(resendCredentials, emailDetails.getAddress(), emailDetails.getSubject(), emailDetails.getBody());
            return;
        }

        final SMTPCredentialsData smtpCredentialsData = this.externalServicesReadPlatformService.getSMTPCredentials();
        final JavaMailSenderImpl mailSender = this.smtpMailSenderFactory.create(smtpCredentialsData);

        try {
            SimpleMailMessage message = new SimpleMailMessage();
            message.setFrom(smtpCredentialsData.getFromEmail());
            message.setTo(emailDetails.getAddress());
            message.setSubject(emailDetails.getSubject());
            message.setText(emailDetails.getBody());
            mailSender.send(message);

        } catch (Exception e) {
            throw new PlatformEmailSendException(e);
        }
    }
}
