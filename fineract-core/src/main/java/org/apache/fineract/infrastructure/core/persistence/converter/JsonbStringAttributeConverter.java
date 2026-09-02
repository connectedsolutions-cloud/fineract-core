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
package org.apache.fineract.infrastructure.core.persistence.converter;

import jakarta.persistence.AttributeConverter;
import jakarta.persistence.Converter;
import java.sql.SQLException;
import lombok.extern.slf4j.Slf4j;
import org.apache.fineract.infrastructure.core.service.database.DatabaseTypeResolver;
import org.postgresql.util.PGobject;

/**
 * JPA AttributeConverter for PostgreSQL JSONB columns. Converts between Java String (JSON) and PostgreSQL's JSONB type.
 * On MySQL, the attribute is passed through as String (JSON type). Uses {@link JsonbConverterContext} for
 * {@link DatabaseTypeResolver} because JPA instantiates converters via reflection without dependency injection.
 */
@Slf4j
@Converter
public class JsonbStringAttributeConverter implements AttributeConverter<String, Object> {

    @Override
    public Object convertToDatabaseColumn(String attribute) {
        DatabaseTypeResolver resolver = JsonbConverterContext.getResolver();
        if (resolver == null) {
            throw new IllegalStateException("JsonbConverterContext not initialized: DatabaseTypeResolver is null. "
                    + "Ensure JsonbConverterContextInitializer runs at startup.");
        }
        if (!resolver.isPostgreSQL()) {
            return attribute;
        }
        try {
            PGobject pg = new PGobject();
            pg.setType("jsonb");
            pg.setValue(attribute);
            if (log.isDebugEnabled()) {
                log.debug("[JsonbStringAttributeConverter] convertToDatabaseColumn: sending as JSONB, value={}", attribute);
            }
            return pg;
        } catch (SQLException e) {
            log.error("Failed to convert String to PostgreSQL JSONB for value: {}", attribute, e);
            throw new IllegalArgumentException("Unable to serialize to jsonb field", e);
        }
    }

    @Override
    public String convertToEntityAttribute(Object dbData) {
        if (dbData == null) {
            return null;
        }
        if (dbData instanceof PGobject pg) {
            return pg.getValue();
        }
        return dbData.toString();
    }
}
