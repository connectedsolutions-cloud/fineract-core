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
package org.apache.fineract.infrastructure.security.datascope;

import org.apache.commons.lang3.StringUtils;

/**
 * Row-level data access policy, orthogonal to capability permissions.
 *
 * <p>
 * Wider values beat narrower ones when resolving from multiple roles. {@code ALL} is unrestricted (full catalog).
 * {@code OFFICE} and {@code ASSIGNED} are opt-in restrictions.
 */
public enum DataScope {

    ASSIGNED(0), OFFICE(1), ALL(2);

    private final int width;

    DataScope(final int width) {
        this.width = width;
    }

    public boolean isUnrestricted() {
        return this == ALL;
    }

    public boolean isWiderThan(final DataScope other) {
        return this.width > other.width;
    }

    public static DataScope fromRoleValue(final String value) {
        if (StringUtils.isBlank(value)) {
            return ALL;
        }
        return parseRequired(value);
    }

    /**
     * User override: blank/null means inherit from roles (empty optional).
     */
    public static DataScope fromUserOverride(final String value) {
        if (StringUtils.isBlank(value)) {
            return null;
        }
        return parseRequired(value);
    }

    public static DataScope parseRequired(final String value) {
        try {
            return DataScope.valueOf(value.trim().toUpperCase());
        } catch (final IllegalArgumentException ex) {
            throw new IllegalArgumentException("Invalid dataScope: " + value);
        }
    }

    public static boolean isValid(final String value) {
        if (StringUtils.isBlank(value)) {
            return true;
        }
        try {
            DataScope.valueOf(value.trim().toUpperCase());
            return true;
        } catch (final IllegalArgumentException ex) {
            return false;
        }
    }
}
