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
package org.apache.fineract.infrastructure.security.service;

import org.apache.fineract.useradministration.domain.AppUser;

/**
 * Request-scoped original actor while the security context holds the impersonated user.
 */
public final class UserImpersonationContext {

    private static final ThreadLocal<AppUser> ORIGINAL_USER = new ThreadLocal<>();

    private UserImpersonationContext() {}

    public static void setOriginalUser(final AppUser user) {
        ORIGINAL_USER.set(user);
    }

    public static AppUser getOriginalUser() {
        return ORIGINAL_USER.get();
    }

    public static boolean isActive() {
        return ORIGINAL_USER.get() != null;
    }

    public static void clear() {
        ORIGINAL_USER.remove();
    }
}
