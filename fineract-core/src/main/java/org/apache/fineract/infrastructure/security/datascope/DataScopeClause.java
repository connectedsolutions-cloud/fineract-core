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

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Extra {@code AND ...} SQL plus positional bind values to append to a portfolio query.
 */
public final class DataScopeClause {

    public static final DataScopeClause NONE = new DataScopeClause("", List.of());
    public static final DataScopeClause DENY = new DataScopeClause(" and 1=0 ", List.of());

    private final String sql;
    private final List<Object> params;

    public DataScopeClause(final String sql, final List<Object> params) {
        this.sql = sql == null ? "" : sql;
        this.params = params == null ? List.of() : List.copyOf(params);
    }

    public boolean isEmpty() {
        return sql.isBlank();
    }

    public String sql() {
        return sql;
    }

    public List<Object> params() {
        return params;
    }

    public void appendTo(final StringBuilder sqlBuilder, final List<Object> dest) {
        sqlBuilder.append(sql);
        dest.addAll(params);
    }

    public Object[] mergeLeading(final Object... leading) {
        final List<Object> all = new ArrayList<>();
        if (leading != null) {
            Collections.addAll(all, leading);
        }
        all.addAll(params);
        return all.toArray();
    }

    public Object[] mergeTrailing(final List<Object> alreadyCollected) {
        final List<Object> all = new ArrayList<>(alreadyCollected);
        all.addAll(params);
        return all.toArray();
    }
}
