package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class MhDteItemComponentPreviewLineData {

    private Long mappingId;
    private String mappingName;
    private String dteAmountType;
    private String source;
    private BigDecimal amount;
    private String matchedClientTypeKey;
}
