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
package org.apache.fineract.portfolio.loanaccount.service;

import com.google.gson.Gson;
import java.sql.Date;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Builds a JSON snapshot of all {@code m_loan} column values for a given loan. Used when marking a loan as ready for
 * comité to persist the state at that moment into {@code original_approval_submission}.
 */
@RequiredArgsConstructor
public class LoanOriginalApprovalSubmissionSnapshotHelper {

    private static final String EXCLUDE_COLUMN = "original_approval_submission";
    private static final String SQL = "SELECT * FROM m_loan WHERE id = ?";

    private final JdbcTemplate jdbcTemplate;
    private final Gson gson = new Gson();

    /**
     * Fetches the current {@code m_loan} row for the given {@code loanId}, builds a key-value map of all columns
     * (excluding {@code original_approval_submission}), converts values to JSON-friendly types, and returns the JSON
     * string.
     *
     * @param loanId
     *            the loan id
     * @return JSON string of column names (snake_case) to values
     */
    public String buildSnapshotJson(Long loanId) {
        Map<String, Object> row = jdbcTemplate.queryForMap(SQL, loanId);
        row.remove(EXCLUDE_COLUMN);

        Map<String, Object> jsonFriendly = new LinkedHashMap<>();
        for (Map.Entry<String, Object> e : row.entrySet()) {
            jsonFriendly.put(e.getKey(), toJsonFriendly(e.getValue()));
        }
        return gson.toJson(jsonFriendly);
    }

    private static Object toJsonFriendly(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Date d) {
            return d.toLocalDate().toString();
        }
        if (value instanceof Timestamp t) {
            return t.toInstant().atOffset(ZoneOffset.UTC).toString();
        }
        if (value instanceof LocalDate ld) {
            return ld.toString();
        }
        if (value instanceof OffsetDateTime odt) {
            return odt.toString();
        }
        if (value instanceof Instant i) {
            return i.toString();
        }
        return value;
    }
}
