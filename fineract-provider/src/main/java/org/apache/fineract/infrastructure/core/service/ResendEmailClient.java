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

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.configuration.data.ResendCredentialsData;
import org.apache.fineract.infrastructure.configuration.data.SmtpConnectionTestResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

@Component
public class ResendEmailClient {

    static final String BASE_URL = "https://api.resend.com";
    static final String USER_AGENT = "fineract-credesal/1.0";
    static final String CONNECTION_TEST_SUBJECT = "Credesal connection test";
    static final String CONNECTION_TEST_BODY = "This is a connection test from Credesal.";

    private static final Logger LOG = LoggerFactory.getLogger(ResendEmailClient.class);
    private static final int TIMEOUT_MS = 10_000;

    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper;

    public ResendEmailClient() {
        this(createRestTemplate());
    }

    ResendEmailClient(final RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
        this.objectMapper = new ObjectMapper();
    }

    public void send(final ResendCredentialsData credentials, final String to, final String subject, final String text) {
        try {
            postEmail(credentials, to, subject, text);
        } catch (PlatformEmailSendException e) {
            throw e;
        } catch (Exception e) {
            throw new PlatformEmailSendException(e);
        }
    }

    public SmtpConnectionTestResult testConnection(final ResendCredentialsData credentials) {
        if (credentials == null || StringUtils.isBlank(credentials.getApiKey())) {
            return SmtpConnectionTestResult.failure("Resend API key is not configured");
        }
        if (StringUtils.isBlank(credentials.getFromEmail())) {
            return SmtpConnectionTestResult.failure("Resend from email is not configured");
        }
        try {
            postEmail(credentials, credentials.getFromEmail(), CONNECTION_TEST_SUBJECT, CONNECTION_TEST_BODY);
            return SmtpConnectionTestResult.success();
        } catch (PlatformEmailSendException e) {
            return SmtpConnectionTestResult.failure(rootMessage(e));
        } catch (Exception e) {
            return SmtpConnectionTestResult.failure(rootMessage(e));
        }
    }

    private void postEmail(final ResendCredentialsData credentials, final String to, final String subject, final String text) {
        final Map<String, Object> body = new LinkedHashMap<>();
        body.put("from", credentials.formattedFrom());
        body.put("to", List.of(to));
        body.put("subject", subject);
        body.put("text", text);

        final HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.setBearerAuth(credentials.getApiKey());
        headers.set(HttpHeaders.USER_AGENT, USER_AGENT);

        final HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
        try {
            restTemplate.exchange(BASE_URL + "/emails", HttpMethod.POST, entity, String.class);
        } catch (HttpStatusCodeException e) {
            LOG.warn("Resend HTTP error status={} body={}", e.getStatusCode().value(), e.getResponseBodyAsString());
            throw new PlatformEmailSendException(new RuntimeException(parseErrorMessage(e)));
        } catch (RestClientException e) {
            throw new PlatformEmailSendException(e);
        }
    }

    private String parseErrorMessage(final HttpStatusCodeException error) {
        final String rawBody = error.getResponseBodyAsString();
        if (StringUtils.isNotBlank(rawBody)) {
            try {
                final JsonNode root = objectMapper.readTree(rawBody);
                final String message = root.path("message").asText(null);
                if (StringUtils.isNotBlank(message)) {
                    return message;
                }
            } catch (Exception ignored) {
                return rawBody;
            }
            return rawBody;
        }
        return "HTTP " + error.getStatusCode().value();
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

    private static RestTemplate createRestTemplate() {
        final SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(TIMEOUT_MS);
        factory.setReadTimeout(TIMEOUT_MS);
        return new RestTemplate(factory);
    }
}
