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

public record ShareSerialAllocation(long startInclusive, long endInclusive) {

    public String reservationValue() {
        return this.startInclusive + "-" + this.endInclusive;
    }

    public static ShareSerialAllocation parse(final String value) {
        final int separator = value == null ? -1 : value.indexOf('-');
        if (separator <= 0 || separator == value.length() - 1) {
            throw new IllegalArgumentException("Share serial reservation is not a range.");
        }
        return new ShareSerialAllocation(Long.parseLong(value.substring(0, separator)), Long.parseLong(value.substring(separator + 1)));
    }
}
