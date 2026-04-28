package org.apache.fineract.portfolio.invoice.data;

import lombok.Builder;
import lombok.Data;
import org.apache.fineract.portfolio.invoice.domain.MhDteItemComponent;

@Data
@Builder
public class MhDteItemComponentData {

    private Long id;
    private String name;
    private String dteAmountType;
    private Long chargeId;
    private String loanComponent;
    private String clientType;
    private String clientTypeKey;
    private String targetUq;

    public static MhDteItemComponentData from(MhDteItemComponent e) {
        return MhDteItemComponentData.builder().id(e.getId()).name(e.getName())
                .dteAmountType(e.getDteAmountType() != null ? e.getDteAmountType().name() : null)
                .chargeId(e.getCharge() != null ? e.getCharge().getId() : null)
                .loanComponent(e.getLoanComponent() != null ? e.getLoanComponent().name() : null).clientType(e.getClientType())
                .clientTypeKey(e.getClientTypeKey()).targetUq(e.getTargetUq()).build();
    }
}
