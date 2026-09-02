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

import java.util.Properties;
import org.apache.fineract.infrastructure.configuration.data.SMTPCredentialsData;
import org.apache.fineract.infrastructure.configuration.data.SmtpConnectionTestResult;
import org.springframework.mail.javamail.JavaMailSenderImpl;
import org.springframework.stereotype.Component;

@Component
public class SmtpMailSenderFactory {

    private static final int SMTP_TIMEOUT_MS = 10_000;

    public JavaMailSenderImpl create(final SMTPCredentialsData credentials) {
        final JavaMailSenderImpl mailSender = new JavaMailSenderImpl();
        mailSender.setHost(credentials.getHost());
        mailSender.setPort(Integer.parseInt(credentials.getPort()));
        mailSender.setUsername(credentials.getUsername());
        mailSender.setPassword(credentials.getPassword());

        final Properties props = mailSender.getJavaMailProperties();
        props.put("mail.transport.protocol", "smtp");
        props.put("mail.smtp.auth", "true");
        props.put("mail.debug", "true");
        props.put("mail.smtp.starttls.enable", "true");
        props.put("mail.smtp.socketFactory.port", Integer.parseInt(credentials.getPort()));
        props.put("mail.smtp.socketFactory.class", "javax.net.ssl.SSLSocketFactory"); // NOSONAR
        props.put("mail.smtp.socketFactory.fallback", "true");
        props.put("mail.smtp.connectiontimeout", String.valueOf(SMTP_TIMEOUT_MS));
        props.put("mail.smtp.timeout", String.valueOf(SMTP_TIMEOUT_MS));
        return mailSender;
    }

    public SmtpConnectionTestResult testConnection(final SMTPCredentialsData credentials) {
        try {
            create(credentials).testConnection();
            return SmtpConnectionTestResult.success();
        } catch (Exception e) {
            return SmtpConnectionTestResult.failure(rootMessage(e));
        }
    }

    private static String rootMessage(final Throwable error) {
        Throwable current = error;
        String message = error.getMessage();
        while (current.getCause() != null && current.getCause() != current) {
            current = current.getCause();
            if (current.getMessage() != null && !current.getMessage().isBlank()) {
                message = current.getMessage();
            }
        }
        return message != null && !message.isBlank() ? message : error.getClass().getSimpleName();
    }
}
