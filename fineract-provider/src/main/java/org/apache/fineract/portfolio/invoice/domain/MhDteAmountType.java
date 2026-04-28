package org.apache.fineract.portfolio.invoice.domain;

import java.util.Arrays;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;

public enum MhDteAmountType {

    ventaNoSuj, ventaExenta, ventaGravada, psv, noGravado;

    public static MhDteAmountType fromApi(String value) {
        if (value == null || value.isBlank()) {
            throw new GeneralPlatformDomainRuleException("validation.msg.mh.dte.amount.type.required", "dteAmountType is required");
        }
        String v = value.trim();
        return Arrays.stream(values()).filter(e -> e.name().equals(v)).findFirst().orElseThrow(
                () -> new GeneralPlatformDomainRuleException("validation.msg.mh.dte.amount.type.invalid", "Invalid dteAmountType: " + value));
    }
}
