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
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import org.apache.fineract.infrastructure.configuration.data.ResendCredentialsData;
import org.apache.fineract.infrastructure.configuration.data.SmtpConnectionTestResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestTemplate;

class ResendEmailClientTest {

    private RestTemplate restTemplate;
    private MockRestServiceServer server;
    private ResendEmailClient underTest;

    @BeforeEach
    void setUp() {
        restTemplate = new RestTemplate();
        server = MockRestServiceServer.bindTo(restTemplate).build();
        underTest = new ResendEmailClient(restTemplate);
    }

    @Test
    void sendPostsToResendWithAuthAndUserAgent() {
        server.expect(requestTo("https://api.resend.com/emails")).andExpect(method(HttpMethod.POST))
                .andExpect(header("Authorization", "Bearer re_test_key")).andExpect(header("User-Agent", "fineract-credesal/1.0"))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andRespond(withSuccess("{\"id\":\"abc-123\"}", MediaType.APPLICATION_JSON));

        underTest.send(credentials(), "user@example.com", "Hello", "Body");

        server.verify();
    }

    @Test
    void sendThrowsWhenResendReturnsUnauthorized() {
        server.expect(requestTo("https://api.resend.com/emails")).andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.UNAUTHORIZED).contentType(MediaType.APPLICATION_JSON)
                        .body("{\"statusCode\":401,\"name\":\"validation_error\",\"message\":\"API key is invalid\"}"));

        assertThatThrownBy(() -> underTest.send(credentials(), "user@example.com", "Hello", "Body"))
                .isInstanceOf(PlatformEmailSendException.class).hasMessageContaining("API key is invalid");

        server.verify();
    }

    @Test
    void sendThrowsWhenResendReturnsForbidden() {
        server.expect(requestTo("https://api.resend.com/emails")).andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.FORBIDDEN).contentType(MediaType.APPLICATION_JSON)
                        .body("{\"statusCode\":403,\"name\":\"restricted_api_key\",\"message\":\"This API key is restricted\"}"));

        assertThatThrownBy(() -> underTest.send(credentials(), "user@example.com", "Hello", "Body"))
                .isInstanceOf(PlatformEmailSendException.class).hasMessageContaining("This API key is restricted");

        server.verify();
    }

    @Test
    void testConnectionSendsTestEmailWhenConfigured() {
        server.expect(requestTo("https://api.resend.com/emails")).andExpect(method(HttpMethod.POST))
                .andExpect(header("Authorization", "Bearer re_test_key")).andExpect(header("User-Agent", "fineract-credesal/1.0"))
                .andRespond(withSuccess("{\"id\":\"test-id\"}", MediaType.APPLICATION_JSON));

        final SmtpConnectionTestResult result = underTest.testConnection(credentials());

        assertThat(result.isConnected()).isTrue();
        assertThat(result.getErrorMessage()).isNull();
        server.verify();
    }

    @Test
    void testConnectionFailsWithoutApiKey() {
        final SmtpConnectionTestResult result = underTest.testConnection(new ResendCredentialsData().setFromEmail("from@example.com"));

        assertThat(result.isConnected()).isFalse();
        assertThat(result.getErrorMessage()).contains("API key");
        server.verify();
    }

    @Test
    void testConnectionFailsWithoutFromEmail() {
        final SmtpConnectionTestResult result = underTest.testConnection(new ResendCredentialsData().setApiKey("re_test_key"));

        assertThat(result.isConnected()).isFalse();
        assertThat(result.getErrorMessage()).contains("from email");
        server.verify();
    }

    @Test
    void testConnectionReturnsResendErrorMessage() {
        server.expect(requestTo("https://api.resend.com/emails")).andExpect(method(HttpMethod.POST))
                .andRespond(withStatus(HttpStatus.FORBIDDEN).contentType(MediaType.APPLICATION_JSON)
                        .body("{\"message\":\"The from address is not verified\"}"));

        final SmtpConnectionTestResult result = underTest.testConnection(credentials());

        assertThat(result.isConnected()).isFalse();
        assertThat(result.getErrorMessage()).isEqualTo("The from address is not verified");
        server.verify();
    }

    private static ResendCredentialsData credentials() {
        return new ResendCredentialsData().setApiKey("re_test_key").setFromEmail("from@example.com").setFromName("Credesal");
    }
}
