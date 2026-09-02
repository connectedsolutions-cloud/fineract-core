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

import static org.assertj.core.api.Assertions.assertThat;

import org.apache.fineract.infrastructure.configuration.data.SMTPCredentialsData;
import org.junit.jupiter.api.Test;
import org.springframework.mail.javamail.JavaMailSenderImpl;

class SmtpMailSenderFactoryTest {

    private final SmtpMailSenderFactory underTest = new SmtpMailSenderFactory();

    @Test
    void createAppliesHostPortAuthTlsAndTimeouts() {
        final SMTPCredentialsData credentials = new SMTPCredentialsData().setUsername("user").setPassword("secret")
                .setHost("smtp.mailgun.org").setPort("2525").setUseTLS(true);

        final JavaMailSenderImpl mailSender = underTest.create(credentials);

        assertThat(mailSender.getHost()).isEqualTo("smtp.mailgun.org");
        assertThat(mailSender.getPort()).isEqualTo(2525);
        assertThat(mailSender.getUsername()).isEqualTo("user");
        assertThat(mailSender.getPassword()).isEqualTo("secret");
        assertThat(mailSender.getJavaMailProperties().getProperty("mail.smtp.starttls.enable")).isEqualTo("true");
        assertThat(mailSender.getJavaMailProperties().getProperty("mail.smtp.auth")).isEqualTo("true");
        assertThat(mailSender.getJavaMailProperties().getProperty("mail.smtp.connectiontimeout")).isEqualTo("10000");
        assertThat(mailSender.getJavaMailProperties().getProperty("mail.smtp.timeout")).isEqualTo("10000");
        assertThat(mailSender.getJavaMailProperties().getProperty("mail.smtp.socketFactory.fallback")).isEqualTo("true");
    }
}
