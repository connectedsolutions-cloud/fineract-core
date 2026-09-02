package org.apache.fineract.portfolio.invoice.domain;

import java.util.Arrays;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;

public enum MhDteLoanComponent {

    PRINCIPAL, INTEREST;

    public static MhDteLoanComponent fromApi(String value) {
        if (value == null || value.isBlank()) {
            throw new GeneralPlatformDomainRuleException("validation.msg.mh.dte.loan.component.required", "loanComponent is required");
        }
        String v = value.trim().toUpperCase();
        return Arrays.stream(values()).filter(e -> e.name().equals(v)).findFirst()
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("validation.msg.mh.dte.loan.component.invalid",
                        "Invalid loanComponent: " + value));
    }
}
