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
package org.apache.fineract.infrastructure.core.service;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.apache.commons.lang3.StringUtils;

/**
 * Utility for merging dimension JSON strings (e.g. product dimensions with loan-level overrides).
 */
public final class DimensionsUtils {

    private static final Gson GSON = new Gson();

    private DimensionsUtils() {}

    /**
     * Merges two dimension JSON strings. Parses both as JSON objects, then merges so that keys from
     * {@code overrideDimensions} take precedence over {@code baseDimensions}. Returns the merged JSON string, or null
     * if both inputs are null/blank.
     *
     * @param baseDimensions
     *            base JSON object (e.g. from loan product); may be null or blank
     * @param overrideDimensions
     *            override JSON object (e.g. from loan application); may be null or blank
     * @return merged JSON string, or null if both are null/blank
     */
    public static String appendDimensions(final String baseDimensions, final String overrideDimensions) {
        final JsonObject base = parseToObject(baseDimensions);
        final JsonObject override = parseToObject(overrideDimensions);
        if (base == null && override == null) {
            return null;
        }
        final JsonObject merged = new JsonObject();
        if (base != null) {
            base.entrySet().forEach(e -> merged.add(e.getKey(), e.getValue()));
        }
        if (override != null) {
            override.entrySet().forEach(e -> merged.add(e.getKey(), e.getValue()));
        }
        return merged.entrySet().isEmpty() ? null : GSON.toJson(merged);
    }

    private static JsonObject parseToObject(final String json) {
        if (StringUtils.isBlank(json)) {
            return null;
        }
        try {
            return JsonParser.parseString(json.trim()).getAsJsonObject();
        } catch (Exception e) {
            return null;
        }
    }
}
