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
package org.apache.fineract.accounting.cutoff;

import java.util.function.Supplier;
import org.springframework.stereotype.Component;

@Component
public class AccountingPostingContext {

    private final ThreadLocal<AccountingPostingOrigin> currentOrigin = ThreadLocal
            .withInitial(() -> AccountingPostingOrigin.NATIVE_OPERATION);

    public AccountingPostingOrigin getOrigin() {
        return currentOrigin.get();
    }

    public void setOrigin(AccountingPostingOrigin origin) {
        currentOrigin.set(origin);
    }

    public void clear() {
        currentOrigin.remove();
    }

    public <T> T executeAs(AccountingPostingOrigin origin, Supplier<T> action) {
        AccountingPostingOrigin previous = getOrigin();
        try {
            setOrigin(origin);
            return action.get();
        } finally {
            setOrigin(previous);
        }
    }
}
