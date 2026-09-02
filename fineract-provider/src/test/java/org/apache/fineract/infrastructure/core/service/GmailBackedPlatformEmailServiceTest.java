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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import org.apache.fineract.infrastructure.configuration.data.ResendCredentialsData;
import org.apache.fineract.infrastructure.configuration.data.SMTPCredentialsData;
import org.apache.fineract.infrastructure.configuration.service.ExternalServicesPropertiesReadPlatformService;
import org.apache.fineract.infrastructure.core.domain.EmailDetail;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSenderImpl;

@ExtendWith(MockitoExtension.class)
class GmailBackedPlatformEmailServiceTest {

    @Mock
    private ExternalServicesPropertiesReadPlatformService readPlatformService;

    @Mock
    private SmtpMailSenderFactory smtpMailSenderFactory;

    @Mock
    private ResendEmailClient resendEmailClient;

    @Mock
    private JavaMailSenderImpl mailSender;

    private GmailBackedPlatformEmailService underTest;

    @BeforeEach
    void setUp() {
        underTest = new GmailBackedPlatformEmailService(readPlatformService, smtpMailSenderFactory, resendEmailClient);
    }

    @Test
    void usesResendWhenApiKeyPresent() {
        when(readPlatformService.getResendCredentials())
                .thenReturn(new ResendCredentialsData().setApiKey("re_live").setFromEmail("from@example.com").setFromName("Credesal"));

        underTest.sendDefinedEmail(emailDetail());

        verify(resendEmailClient).send(any(ResendCredentialsData.class), eq("user@example.com"), eq("Subject"), eq("Body"));
        verifyNoInteractions(smtpMailSenderFactory);
        verify(readPlatformService, never()).getSMTPCredentials();
    }

    @Test
    void usesSmtpWhenApiKeyBlank() {
        when(readPlatformService.getResendCredentials()).thenReturn(new ResendCredentialsData());
        final SMTPCredentialsData smtpCredentials = new SMTPCredentialsData().setUsername("user").setPassword("secret")
                .setHost("localhost").setPort("3025").setFromEmail("from@example.com");
        when(readPlatformService.getSMTPCredentials()).thenReturn(smtpCredentials);
        when(smtpMailSenderFactory.create(smtpCredentials)).thenReturn(mailSender);

        underTest.sendDefinedEmail(emailDetail());

        verify(mailSender).send(any(SimpleMailMessage.class));
        verifyNoInteractions(resendEmailClient);
    }

    private static EmailDetail emailDetail() {
        return new EmailDetail("Subject", "Body", "user@example.com", "User");
    }
}
