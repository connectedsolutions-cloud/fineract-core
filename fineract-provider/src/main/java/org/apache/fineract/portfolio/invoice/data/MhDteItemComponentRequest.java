package org.apache.fineract.portfolio.invoice.data;

import lombok.Data;

@Data
public class MhDteItemComponentRequest {

    private String name;
    private String dteAmountType;
    private Long chargeId;
    private String loanComponent;
    private String clientType;
}
