package org.apache.fineract.portfolio.invoice.data;

import java.math.BigDecimal;
import java.time.LocalDate;
import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class MhDteItemComponentJournalLineData {

    private Long id;
    private Long glAccountId;
    private BigDecimal amount;
    private boolean debit;
    private LocalDate entryDate;
    private String description;
}
