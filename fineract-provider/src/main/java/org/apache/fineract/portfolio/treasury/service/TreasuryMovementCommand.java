package org.apache.fineract.portfolio.treasury.service;

import java.math.BigDecimal;
import java.time.LocalDate;

public record TreasuryMovementCommand(String type, LocalDate businessDate, LocalDate valueDate, Long officeId, BigDecimal amount,
        String direction, Long bankAccountId, Long destinationBankAccountId, Long counterGlAccountId, String bankReference,
        String payeeName, Long staffId, String note) {
}
