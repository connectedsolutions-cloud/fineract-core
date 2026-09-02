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
package org.apache.fineract.portfolio.namingsequence.service;

import java.util.LinkedHashMap;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.portfolio.namingsequence.CredesalNamingCodes;
import org.apache.fineract.portfolio.namingsequence.CredesalNamingNamespace;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class CredesalProductNumberingSupport {

    private final JdbcTemplate jdbcTemplate;

    public String assignOnCreate(final JsonCommand command, final CredesalNamingNamespace namespace, final String tableName) {
        final String code = readValidated(command, namespace);
        assertUnique(tableName, code, null);
        return code;
    }

    public String readValidated(final JsonCommand command, final CredesalNamingNamespace namespace) {
        if (!command.parameterExists(CredesalNamingCodes.PARAM_NAME)) {
            return null;
        }
        return validate(namespace, command.stringValueOfParameterNamedAllowingNull(CredesalNamingCodes.PARAM_NAME));
    }

    public String validate(final CredesalNamingNamespace namespace, final String numberingCode) {
        final String normalized = CredesalNamingCodes.normalize(numberingCode);
        if (normalized == null) {
            return null;
        }
        final String error = CredesalNamingCodes.validationError(namespace, normalized);
        if (error != null) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.naming.code.invalid", error, normalized);
        }
        return normalized;
    }

    public void assertUnique(final String tableName, final String numberingCode, final Long excludeProductId) {
        if (numberingCode == null) {
            return;
        }
        final String sql = excludeProductId == null
                ? "select count(1) from " + tableName + " where numbering_code = ?"
                : "select count(1) from " + tableName + " where numbering_code = ? and id <> ?";
        final Integer count = excludeProductId == null ? jdbcTemplate.queryForObject(sql, Integer.class, numberingCode)
                : jdbcTemplate.queryForObject(sql, Integer.class, numberingCode, excludeProductId);
        if (count != null && count > 0) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.naming.code.duplicate",
                    "Numbering code `" + numberingCode + "` is already assigned to another product.", numberingCode);
        }
    }

    public Map<String, Object> applyUpdate(final JsonCommand command, final CredesalNamingNamespace namespace, final String currentCode,
            final String tableName, final Long productId) {
        final Map<String, Object> changes = new LinkedHashMap<>();
        if (!command.parameterExists(CredesalNamingCodes.PARAM_NAME)) {
            return changes;
        }
        final String requested = validate(namespace, command.stringValueOfParameterNamedAllowingNull(CredesalNamingCodes.PARAM_NAME));
        if (StringUtils.equals(StringUtils.trimToNull(currentCode), requested)) {
            return changes;
        }
        if (StringUtils.isNotBlank(currentCode) && !StringUtils.equals(currentCode, requested)) {
            throw new GeneralPlatformDomainRuleException("error.msg.credesal.naming.code.immutable",
                    "Numbering code cannot be changed once it has been set.", currentCode);
        }
        assertUnique(tableName, requested, productId);
        changes.put(CredesalNamingCodes.PARAM_NAME, requested);
        return changes;
    }
}
