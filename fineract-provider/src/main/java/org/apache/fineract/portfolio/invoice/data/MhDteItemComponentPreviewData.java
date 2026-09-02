package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class MhDteItemComponentPreviewData {

    private Long loanTransactionId;
    private String clientTypeInput;
    private List<MhDteItemComponentPreviewLineData> lines;
    private Map<String, BigDecimal> totalsByDteAmountType;
    private List<String> warnings;
    private List<MhDteItemComponentJournalLineData> journalEntries;

    public static MhDteItemComponentPreviewData empty(Long loanTransactionId, String clientTypeInput) {
        return MhDteItemComponentPreviewData.builder().loanTransactionId(loanTransactionId).clientTypeInput(clientTypeInput)
                .lines(List.of()).totalsByDteAmountType(new LinkedHashMap<>()).warnings(new ArrayList<>()).journalEntries(List.of())
                .build();
    }
}
