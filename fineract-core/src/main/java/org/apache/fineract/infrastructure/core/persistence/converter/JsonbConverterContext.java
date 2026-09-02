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

import org.apache.fineract.infrastructure.core.service.database.DatabaseTypeResolver;

/**
 * Static holder for {@link DatabaseTypeResolver} so that {@link JsonbStringAttributeConverter} can access it.
 * JPA/EclipseLink instantiates converters via reflection without DI, so we use this context instead of constructor
 * injection. Set by {@link JsonbConverterContextInitializer}.
 */
public final class JsonbConverterContext {

    private static volatile DatabaseTypeResolver resolver;

    private JsonbConverterContext() {}

    public static void setResolver(DatabaseTypeResolver databaseTypeResolver) {
        resolver = databaseTypeResolver;
    }

    public static DatabaseTypeResolver getResolver() {
        return resolver;
    }
}
