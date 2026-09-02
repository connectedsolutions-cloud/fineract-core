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
package org.apache.fineract.portfolio.savings.service;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SavingsAccountWritePlatformServiceJpaRepositoryImplTest {

    @Test
    void shouldRecognizeNativeGeneratedTransactionReferences() {
        assertThat(SavingsAccountWritePlatformServiceJpaRepositoryImpl.isNativeGeneratedTransactionReference(null)).isTrue();
        assertThat(SavingsAccountWritePlatformServiceJpaRepositoryImpl.isNativeGeneratedTransactionReference(" ")).isTrue();
        assertThat(SavingsAccountWritePlatformServiceJpaRepositoryImpl
                .isNativeGeneratedTransactionReference("a30befdb-6950-43f8-9af8-b4e61c45b852")).isTrue();
    }

    @Test
    void shouldRejectSourceManagedTransactionReferences() {
        assertThat(SavingsAccountWritePlatformServiceJpaRepositoryImpl
                .isNativeGeneratedTransactionReference("arissto:savings:001:001:0000000025:interest:2026-06-30")).isFalse();
        assertThat(SavingsAccountWritePlatformServiceJpaRepositoryImpl
                .isNativeGeneratedTransactionReference("a30befdb695043f89af8b4e61c45b852")).isFalse();
    }
}
