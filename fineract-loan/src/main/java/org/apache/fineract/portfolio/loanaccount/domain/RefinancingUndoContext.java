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

/** Only the dependency-locked refinance orchestration may authorize the native successor undo. */
public final class RefinancingUndoContext implements AutoCloseable {

    private static final ThreadLocal<Long> LOAN = new ThreadLocal<>();

    private RefinancingUndoContext(Long loanId) {
        if (LOAN.get() != null) {
            throw new IllegalStateException("Nested refinance undo");
        }
        LOAN.set(loanId);
    }

    public static RefinancingUndoContext open(Long loanId) {
        return new RefinancingUndoContext(loanId);
    }

    public static boolean permits(Long loanId) {
        return loanId != null && loanId.equals(LOAN.get());
    }

    @Override
    public void close() {
        LOAN.remove();
    }
}
