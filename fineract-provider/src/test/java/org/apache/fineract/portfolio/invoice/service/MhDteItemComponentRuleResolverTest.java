package org.apache.fineract.portfolio.invoice.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

import java.util.List;
import org.apache.fineract.portfolio.invoice.domain.MhDteAmountType;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponent;
import org.apache.fineract.portfolio.invoice.domain.MhDteLoanComponent;
import org.junit.jupiter.api.Test;

class MhDteItemComponentRuleResolverTest {

    private final MhDteItemComponentRuleResolver resolver = new MhDteItemComponentRuleResolver();

    @Test
    void picksSpecificClientTypeBeforeFallback() {
        MhDteItemComponent specific = MhDteItemComponent.create("specific", MhDteAmountType.ventaExenta, null, MhDteLoanComponent.INTEREST,
                "VIP", "VIP", "L_INTEREST");
        MhDteItemComponent fallback = MhDteItemComponent.create("fallback", MhDteAmountType.ventaNoSuj, null, MhDteLoanComponent.INTEREST, null,
                MhDteItemComponentRuleResolver.DEFAULT_CLIENT_TYPE_KEY, "L_INTEREST");

        MhDteItemComponent matched = resolver.pickMapping(List.of(fallback, specific), "L_INTEREST", "VIP");

        assertNotNull(matched);
        assertEquals("specific", matched.getName());
    }

    @Test
    void fallsBackToDefaultClientType() {
        MhDteItemComponent fallback = MhDteItemComponent.create("fallback", MhDteAmountType.ventaNoSuj, null, MhDteLoanComponent.PRINCIPAL, null,
                MhDteItemComponentRuleResolver.DEFAULT_CLIENT_TYPE_KEY, "L_PRINCIPAL");

        MhDteItemComponent matched = resolver.pickMapping(List.of(fallback), "L_PRINCIPAL", "UNKNOWN");

        assertNotNull(matched);
        assertEquals("fallback", matched.getName());
    }

    @Test
    void returnsNullWhenTargetDoesNotExist() {
        MhDteItemComponent fallback = MhDteItemComponent.create("fallback", MhDteAmountType.ventaNoSuj, null, MhDteLoanComponent.PRINCIPAL, null,
                MhDteItemComponentRuleResolver.DEFAULT_CLIENT_TYPE_KEY, "L_PRINCIPAL");

        MhDteItemComponent matched = resolver.pickMapping(List.of(fallback), "C_123", "VIP");

        assertNull(matched);
    }
}

