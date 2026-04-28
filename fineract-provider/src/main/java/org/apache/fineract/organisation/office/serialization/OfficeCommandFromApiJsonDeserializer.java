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
package org.apache.fineract.organisation.office.serialization;

import com.google.gson.JsonElement;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.data.ApiParameterError;
import org.apache.fineract.infrastructure.core.data.DataValidatorBuilder;
import org.apache.fineract.infrastructure.core.exception.InvalidJsonException;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.serialization.FromJsonHelper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/**
 * Deserializer of JSON for office API.
 */
@Component
public final class OfficeCommandFromApiJsonDeserializer {

    public static final String PARENT_ID = "parentId";
    public static final String NAME = "name";
    public static final String OPENING_DATE = "openingDate";
    public static final String EXTERNAL_ID = "externalId";
    public static final String MH_NIT = "mhNit";
    public static final String MH_PASSWORD_PRI = "mhPasswordPri";
    public static final String MH_FIRMA_SECRET = "mhFirmaSecret";
    public static final String MH_SIGNING_API_KEY = "mhSigningApiKey";
    public static final String MH_COD_ESTABLE = "mhCodEstable";
    public static final String MH_COD_PUNTO_VENTA = "mhCodPuntoVenta";
    public static final String LOCALE = "locale";
    public static final String DATE_FORMAT = "dateFormat";
    /**
     * The parameters supported for this command.
     */
    private static final Set<String> SUPPORTED_PARAMETERS = new HashSet<>(
            Arrays.asList(NAME, PARENT_ID, OPENING_DATE, EXTERNAL_ID, MH_NIT, MH_PASSWORD_PRI, MH_FIRMA_SECRET, MH_SIGNING_API_KEY,
                    MH_COD_ESTABLE, MH_COD_PUNTO_VENTA, LOCALE, DATE_FORMAT));

    private final FromJsonHelper fromApiJsonHelper;

    @Autowired
    public OfficeCommandFromApiJsonDeserializer(final FromJsonHelper fromApiJsonHelper) {
        this.fromApiJsonHelper = fromApiJsonHelper;
    }

    public void validateForCreate(final String json) {
        if (StringUtils.isBlank(json)) {
            throw new InvalidJsonException();
        }

        final Type typeOfMap = new TypeToken<Map<String, Object>>() {}.getType();
        this.fromApiJsonHelper.checkForUnsupportedParameters(typeOfMap, json, SUPPORTED_PARAMETERS);

        final List<ApiParameterError> dataValidationErrors = new ArrayList<>();
        final DataValidatorBuilder baseDataValidator = new DataValidatorBuilder(dataValidationErrors).resource("office");

        final JsonElement element = this.fromApiJsonHelper.parse(json);

        final String name = this.fromApiJsonHelper.extractStringNamed(NAME, element);
        baseDataValidator.reset().parameter(NAME).value(name).notBlank().notExceedingLengthOf(100);

        final LocalDate openingDate = this.fromApiJsonHelper.extractLocalDateNamed(OPENING_DATE, element);
        baseDataValidator.reset().parameter(OPENING_DATE).value(openingDate).notNull();

        if (this.fromApiJsonHelper.parameterExists(EXTERNAL_ID, element)) {
            final String externalId = this.fromApiJsonHelper.extractStringNamed(EXTERNAL_ID, element);
            baseDataValidator.reset().parameter(EXTERNAL_ID).value(externalId).notExceedingLengthOf(100);
        }

        if (this.fromApiJsonHelper.parameterExists(PARENT_ID, element)) {
            final Long parentId = this.fromApiJsonHelper.extractLongNamed(PARENT_ID, element);
            baseDataValidator.reset().parameter(PARENT_ID).value(parentId).notNull().integerGreaterThanZero();
        }

        validateMhFields(element, baseDataValidator);

        throwExceptionIfValidationWarningsExist(dataValidationErrors);
    }

    private void throwExceptionIfValidationWarningsExist(final List<ApiParameterError> dataValidationErrors) {
        if (!dataValidationErrors.isEmpty()) {
            throw new PlatformApiDataValidationException("validation.msg.validation.errors.exist", "Validation errors exist.",
                    dataValidationErrors);
        }
    }

    public void validateForUpdate(final String json) {
        if (StringUtils.isBlank(json)) {
            throw new InvalidJsonException();
        }

        final Type typeOfMap = new TypeToken<Map<String, Object>>() {}.getType();
        this.fromApiJsonHelper.checkForUnsupportedParameters(typeOfMap, json, SUPPORTED_PARAMETERS);

        final List<ApiParameterError> dataValidationErrors = new ArrayList<>();
        final DataValidatorBuilder baseDataValidator = new DataValidatorBuilder(dataValidationErrors).resource("office");

        final JsonElement element = this.fromApiJsonHelper.parse(json);

        if (this.fromApiJsonHelper.parameterExists(NAME, element)) {
            final String name = this.fromApiJsonHelper.extractStringNamed(NAME, element);
            baseDataValidator.reset().parameter(NAME).value(name).notBlank().notExceedingLengthOf(100);
        }

        if (this.fromApiJsonHelper.parameterExists(OPENING_DATE, element)) {
            final LocalDate openingDate = this.fromApiJsonHelper.extractLocalDateNamed(OPENING_DATE, element);
            baseDataValidator.reset().parameter(OPENING_DATE).value(openingDate).notNull();
        }

        if (this.fromApiJsonHelper.parameterExists(EXTERNAL_ID, element)) {
            final String externalId = this.fromApiJsonHelper.extractStringNamed(EXTERNAL_ID, element);
            baseDataValidator.reset().parameter(EXTERNAL_ID).value(externalId).notExceedingLengthOf(100);
        }

        if (this.fromApiJsonHelper.parameterExists(PARENT_ID, element)) {
            final Long parentId = this.fromApiJsonHelper.extractLongNamed(PARENT_ID, element);
            baseDataValidator.reset().parameter(PARENT_ID).value(parentId).notNull().integerGreaterThanZero();
        }

        validateMhFields(element, baseDataValidator);

        throwExceptionIfValidationWarningsExist(dataValidationErrors);
    }

    private void validateMhFields(JsonElement element, DataValidatorBuilder baseDataValidator) {
        if (this.fromApiJsonHelper.parameterExists(MH_NIT, element)) {
            final String mhNit = this.fromApiJsonHelper.extractStringNamed(MH_NIT, element);
            baseDataValidator.reset().parameter(MH_NIT).value(mhNit).notExceedingLengthOf(20);
        }
        if (this.fromApiJsonHelper.parameterExists(MH_PASSWORD_PRI, element)) {
            final String mhPasswordPri = this.fromApiJsonHelper.extractStringNamed(MH_PASSWORD_PRI, element);
            baseDataValidator.reset().parameter(MH_PASSWORD_PRI).value(mhPasswordPri).notExceedingLengthOf(500);
        }
        if (this.fromApiJsonHelper.parameterExists(MH_FIRMA_SECRET, element)) {
            final String mhFirmaSecret = this.fromApiJsonHelper.extractStringNamed(MH_FIRMA_SECRET, element);
            baseDataValidator.reset().parameter(MH_FIRMA_SECRET).value(mhFirmaSecret).notExceedingLengthOf(255);
        }
        if (this.fromApiJsonHelper.parameterExists(MH_SIGNING_API_KEY, element)) {
            final String mhSigningApiKey = this.fromApiJsonHelper.extractStringNamed(MH_SIGNING_API_KEY, element);
            baseDataValidator.reset().parameter(MH_SIGNING_API_KEY).value(mhSigningApiKey).notExceedingLengthOf(255);
        }
        if (this.fromApiJsonHelper.parameterExists(MH_COD_ESTABLE, element)) {
            final String mhCodEstable = this.fromApiJsonHelper.extractStringNamed(MH_COD_ESTABLE, element);
            baseDataValidator.reset().parameter(MH_COD_ESTABLE).value(mhCodEstable).notExceedingLengthOf(20);
        }
        if (this.fromApiJsonHelper.parameterExists(MH_COD_PUNTO_VENTA, element)) {
            final String mhCodPuntoVenta = this.fromApiJsonHelper.extractStringNamed(MH_COD_PUNTO_VENTA, element);
            baseDataValidator.reset().parameter(MH_COD_PUNTO_VENTA).value(mhCodPuntoVenta).notExceedingLengthOf(20);
        }
    }
}
