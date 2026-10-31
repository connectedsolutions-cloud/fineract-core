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
package org.apache.fineract.portfolio.loanaccount.domain;

/** Scopes withheld committee charges to their actual native refinance origination. */
public final class RefinancingOriginationContext implements AutoCloseable {

    private static final ThreadLocal<Long> LOAN = new ThreadLocal<>();

    private RefinancingOriginationContext(Long id) {
        if (LOAN.get() != null) {
            throw new IllegalStateException("Nested refinance origination");
        }
        LOAN.set(id);
    }

    public static RefinancingOriginationContext open(Long id) {
        return new RefinancingOriginationContext(id);
    }

    public static boolean applies(Long id) {
        return id != null && id.equals(LOAN.get());
    }

    @Override
    public void close() {
        LOAN.remove();
    }
}
