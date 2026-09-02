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
package org.apache.fineract.portfolio.namingsequence;

import java.util.Optional;
import java.util.regex.Pattern;
import org.apache.commons.lang3.StringUtils;

public final class CredesalNamingCodes {

    public static final String PARAM_NAME = "numberingCode";
    public static final String AFFILIATION_PATTERN = "^\\d{10}$";
    public static final int PARTY_PREFIX_LENGTH = 5;

    private static final Pattern AFFILIATION = Pattern.compile(AFFILIATION_PATTERN);
    private static final Pattern LOAN_CODE = Pattern.compile("^3[A-Z]1$");
    private static final Pattern SAVINGS_CODE = Pattern.compile("^4V1$|^5D[1236789]$");
    private static final Pattern DISABLED_DPF_CODE = Pattern.compile("^5D[45]$");
    private static final Pattern CERTIFICATE_CODE = Pattern.compile("^1A[CP]$");

    private CredesalNamingCodes() {}

    public static String normalize(final String numberingCode) {
        if (StringUtils.isBlank(numberingCode)) {
            return null;
        }
        return numberingCode.trim().toUpperCase();
    }

    public static boolean isValid(final CredesalNamingNamespace namespace, final String numberingCode) {
        return validationError(namespace, numberingCode) == null;
    }

    public static String validationError(final CredesalNamingNamespace namespace, final String numberingCode) {
        final String normalized = normalize(numberingCode);
        if (normalized == null) {
            return null;
        }
        if (namespace == CredesalNamingNamespace.VISTA_PASSBOOK) {
            return "Passbook numbering does not use a product code.";
        }
        if (namespace == CredesalNamingNamespace.SAVINGS && DISABLED_DPF_CODE.matcher(normalized).matches()) {
            return "Numbering codes 5D4 and 5D5 are not approved.";
        }
        final Pattern pattern = switch (namespace) {
            case LOAN -> LOAN_CODE;
            case SAVINGS -> SAVINGS_CODE;
            case SHARE_CERTIFICATE -> CERTIFICATE_CODE;
            case VISTA_PASSBOOK -> null;
        };
        if (pattern != null && !pattern.matcher(normalized).matches()) {
            return "Numbering code '" + normalized + "' is not valid for " + namespace + ".";
        }
        return null;
    }

    public static Optional<String> extractPartyPrefix(final String affiliationNumber) {
        if (affiliationNumber == null || !AFFILIATION.matcher(affiliationNumber).matches()) {
            return Optional.empty();
        }
        return Optional.of(affiliationNumber.substring(affiliationNumber.length() - PARTY_PREFIX_LENGTH));
    }

    public static String composePrefix(final String partyPrefix, final String numberingCode) {
        if (StringUtils.isBlank(numberingCode)) {
            return StringUtils.defaultString(partyPrefix);
        }
        return StringUtils.defaultString(partyPrefix) + numberingCode;
    }

    public static String formatValue(final String prefix, final int ordinal, final int width) {
        return prefix + StringUtils.leftPad(Integer.toString(ordinal), width, '0');
    }

    public static Optional<Integer> parseOrdinal(final String value, final String prefix, final int width) {
        if (value == null || prefix == null || !value.startsWith(prefix) || value.length() != prefix.length() + width) {
            return Optional.empty();
        }
        final String suffix = value.substring(prefix.length());
        if (!suffix.chars().allMatch(Character::isDigit)) {
            return Optional.empty();
        }
        return Optional.of(Integer.parseInt(suffix));
    }
}
