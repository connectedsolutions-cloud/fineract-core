package org.apache.fineract.portfolio.invoice.service;

import java.util.List;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponent;
import org.apache.fineract.portfolio.invoice.domain.MhDteLoanComponent;
import org.springframework.stereotype.Component;

@Component
public class MhDteItemComponentRuleResolver {

    public static final String DEFAULT_CLIENT_TYPE_KEY = "*";

    public MhDteItemComponent pickMapping(List<MhDteItemComponent> all, String targetUq, String requestedClientKey) {
        List<MhDteItemComponent> forTarget = all.stream().filter(m -> targetUq.equals(m.getTargetUq())).toList();
        if (forTarget.isEmpty()) {
            return null;
        }
        return forTarget.stream()
                .filter(m -> !DEFAULT_CLIENT_TYPE_KEY.equals(m.getClientTypeKey()) && requestedClientKey.equals(m.getClientTypeKey()))
                .findFirst().orElseGet(() -> forTarget.stream().filter(m -> DEFAULT_CLIENT_TYPE_KEY.equals(m.getClientTypeKey())).findFirst()
                        .orElse(null));
    }

    public String normalizeClientTypeKey(String clientType) {
        if (clientType == null) {
            return DEFAULT_CLIENT_TYPE_KEY;
        }
        String t = clientType.trim();
        return t.isEmpty() ? DEFAULT_CLIENT_TYPE_KEY : t;
    }

    public String targetUqCharge(long chargeId) {
        return "C_" + chargeId;
    }

    public String targetUqLoan(MhDteLoanComponent c) {
        return "L_" + c.name();
    }
}

