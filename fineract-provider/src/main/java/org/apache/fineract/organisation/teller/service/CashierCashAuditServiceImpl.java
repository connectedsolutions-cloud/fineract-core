/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 */
package org.apache.fineract.organisation.teller.service;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.domain.JdbcSupport;
import org.apache.fineract.infrastructure.core.service.SearchParameters;
import org.apache.fineract.organisation.teller.data.CashierCashAuditData;
import org.apache.fineract.organisation.teller.exception.CashierNotFoundException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * Deliberately uses explicit cashier IDs. The legacy teller summary's staff/date fallback is not a safe close basis.
 * Unverified events and unattributed candidates are exposed rather than silently assigned to the cashier.
 */
@Service
@RequiredArgsConstructor
public class CashierCashAuditServiceImpl implements CashierCashAuditService {

    private static final String IN = "CASH_IN";
    private static final String OUT = "CASH_OUT";
    private static final String ALLOCATE = "ALLOCATE";
    private static final String SETTLE = "SETTLE";
    private static final String NON_CASH = "NON_CASH";
    private static final String UNVERIFIED = "UNVERIFIED";
    private static final String REVERSED = "REVERSED";
    private static final String DISPLAY = "DISPLAY_ONLY";

    private final JdbcTemplate jdbcTemplate;
    private final TellerManagementReadPlatformService tellerReadPlatformService;

    @Override
    public CashierCashAuditData audit(Long tellerId, Long cashierId, String currencyCode) {
        final List<Session> sessions = jdbcTemplate.query("""
                SELECT c.id, c.start_date, c.end_date, c.opening_balance
                FROM m_cashiers c JOIN m_tellers t ON t.id = c.teller_id
                WHERE c.id = ? AND t.id = ?
                """, (rs, rowNum) -> new Session(JdbcSupport.getLocalDate(rs, "start_date"),
                JdbcSupport.getLocalDate(rs, "end_date"), rs.getBigDecimal("opening_balance")), cashierId, tellerId);
        if (sessions.isEmpty()) {
            throw new CashierNotFoundException(cashierId);
        }
        final Session session = sessions.get(0);
        final List<CashierCashAuditData.Event> events = new ArrayList<>();
        addTellerEvents(events, cashierId, currencyCode, session);
        addProductEvents(events, "LOAN", "m_loan_transaction", "loan_transaction_type_enum", "m_loan", "loan_id", cashierId,
                currencyCode, session);
        addProductEvents(events, "SAVINGS", "m_savings_account_transaction", "savings_transaction_type_enum", "m_savings_account",
                "savings_account_id", cashierId, currencyCode, session);
        addClientEvents(events, cashierId, currencyCode, session);

        BigDecimal allocations = BigDecimal.ZERO;
        BigDecimal cashReceipts = BigDecimal.ZERO;
        BigDecimal cashPayouts = BigDecimal.ZERO;
        BigDecimal settlements = BigDecimal.ZERO;
        int unverified = 0;
        for (CashierCashAuditData.Event event : events) {
            switch (event.classification()) {
                case ALLOCATE -> allocations = allocations.add(event.amount());
                case IN -> cashReceipts = cashReceipts.add(event.amount());
                case OUT -> cashPayouts = cashPayouts.add(event.amount());
                case SETTLE -> settlements = settlements.add(event.amount());
                case UNVERIFIED -> unverified++;
                default -> { }
            }
        }
        BigDecimal opening = session.openingCash() == null ? BigDecimal.ZERO : session.openingCash();
        BigDecimal expected = opening.add(allocations).add(cashReceipts).subtract(cashPayouts).subtract(settlements);
        int candidates = countUnattributedCandidates(cashierId, currencyCode);
        BigDecimal legacyExpected = opening.add(tellerReadPlatformService.retrieveCashierTransactionsWithSummary(cashierId, false,
                null, null, currencyCode, SearchParameters.builder().limit(1).build()).getNetCash());
        return new CashierCashAuditData(tellerId, cashierId, currencyCode, Instant.now(), opening, allocations, cashReceipts,
                cashPayouts, settlements, expected, legacyExpected, unverified, candidates, List.copyOf(events));
    }

    private void addTellerEvents(List<CashierCashAuditData.Event> events, Long cashierId, String currencyCode, Session session) {
        final String sql = """
                SELECT id, txn_type, txn_amount, txn_date
                FROM m_cashier_transactions
                WHERE cashier_id = ? AND currency_code = ?
                ORDER BY txn_date, id
                """;
        events.addAll(jdbcTemplate.query(sql, (rs, rowNum) -> {
            int type = rs.getInt("txn_type");
            LocalDate date = JdbcSupport.getLocalDate(rs, "txn_date");
            String classification = switch (type) {
                case 101 -> ALLOCATE;
                case 102 -> SETTLE;
                case 103 -> IN;
                case 104 -> OUT;
                case 105, 106 -> DISPLAY;
                default -> UNVERIFIED;
            };
            BigDecimal amount = rs.getBigDecimal("txn_amount");
            return event("TELLER", rs.getLong("id"), date, String.valueOf(type), classification, amount, false, cashierId, session);
        }, cashierId, currencyCode));
    }

    private void addProductEvents(List<CashierCashAuditData.Event> events, String source, String table, String enumName,
            String accountTable, String accountColumn, Long cashierId, String currencyCode, Session session) {
        // Identifiers are fixed constants at each call site, never request input.
        final String sql = "SELECT tx.id, tx.transaction_date, tx.amount, tx.is_reversed, e.enum_value, "
                + "tx.payment_detail_id, pt.is_cash_payment FROM " + table + " tx "
                + "JOIN " + accountTable + " account_ ON account_.id = tx." + accountColumn + " "
                + "LEFT JOIN r_enum_value e ON e.enum_id = tx.transaction_type_enum AND e.enum_name = ? "
                + "LEFT JOIN m_payment_detail pd ON pd.id = tx.payment_detail_id "
                + "LEFT JOIN m_payment_type pt ON pt.id = pd.payment_type_id "
                + "WHERE tx.cashier_id = ? AND account_.currency_code = ? ORDER BY tx.transaction_date, tx.id";
        events.addAll(jdbcTemplate.query(sql, (rs, rowNum) -> {
            String operation = rs.getString("enum_value");
            boolean reversed = rs.getBoolean("is_reversed");
            String classification = classifyProduct(source, operation, rs.getObject("payment_detail_id") != null,
                    (Boolean) rs.getObject("is_cash_payment"), reversed);
            return event(source, rs.getLong("id"), JdbcSupport.getLocalDate(rs, "transaction_date"), operation, classification,
                    rs.getBigDecimal("amount"), reversed, cashierId, session);
        }, enumName, cashierId, currencyCode));
    }

    private void addClientEvents(List<CashierCashAuditData.Event> events, Long cashierId, String currencyCode, Session session) {
        final String sql = """
                SELECT tx.id, tx.transaction_date, tx.amount, tx.is_reversed, e.enum_value,
                       tx.payment_detail_id, pt.is_cash_payment
                FROM m_client_transaction tx
                LEFT JOIN r_enum_value e ON e.enum_id = tx.transaction_type_enum
                     AND e.enum_name = 'client_transaction_type_enum'
                LEFT JOIN m_payment_detail pd ON pd.id = tx.payment_detail_id
                LEFT JOIN m_payment_type pt ON pt.id = pd.payment_type_id
                WHERE tx.cashier_id = ? AND tx.currency_code = ?
                ORDER BY tx.transaction_date, tx.id
                """;
        events.addAll(jdbcTemplate.query(sql, (rs, rowNum) -> {
            String operation = rs.getString("enum_value");
            boolean reversed = rs.getBoolean("is_reversed");
            String classification = classifyProduct("CLIENT", operation, rs.getObject("payment_detail_id") != null,
                    (Boolean) rs.getObject("is_cash_payment"), reversed);
            return event("CLIENT", rs.getLong("id"), JdbcSupport.getLocalDate(rs, "transaction_date"), operation, classification,
                    rs.getBigDecimal("amount"), reversed, cashierId, session);
        }, cashierId, currencyCode));
    }

    static String classifyProduct(String source, String operation, boolean hasPaymentDetail, Boolean cashPayment, boolean reversed) {
        if (reversed) {
            return REVERSED;
        }
        if (Boolean.FALSE.equals(cashPayment)) {
            return NON_CASH;
        }
        if (!hasPaymentDetail || cashPayment == null || operation == null) {
            return UNVERIFIED;
        }
        String kind = operation.toUpperCase(Locale.ROOT);
        return switch (source) {
            case "LOAN" -> switch (kind) {
                case "REPAYMENT", "RECOVERY_REPAYMENT", "CHARGE_PAYMENT" -> IN;
                // The loan transaction amount can exceed cash actually handed over after withheld charges.
                case "DISBURSEMENT" -> UNVERIFIED;
                default -> UNVERIFIED;
            };
            case "SAVINGS" -> switch (kind) {
                case "DEPOSIT" -> IN;
                case "WITHDRAWAL" -> OUT;
                default -> UNVERIFIED;
            };
            case "CLIENT" -> "PAY_CHARGE".equals(kind) ? IN : UNVERIFIED;
            default -> UNVERIFIED;
        };
    }

    private CashierCashAuditData.Event event(String source, Long id, LocalDate date, String operation, String classification,
            BigDecimal amount, boolean reversed, Long cashierId, Session session) {
        if (amount == null || amount.signum() < 0 || date == null || date.isBefore(session.startDate())
                || session.endDate() != null && date.isAfter(session.endDate())) {
            classification = UNVERIFIED;
        }
        return new CashierCashAuditData.Event(source, id, date, operation, classification, amount == null ? BigDecimal.ZERO : amount,
                reversed, cashierId);
    }

    private int countUnattributedCandidates(Long cashierId, String currencyCode) {
        int count = 0;
        count += candidateCount("m_loan_transaction", "m_loan", "loan_id", cashierId, currencyCode);
        count += candidateCount("m_savings_account_transaction", "m_savings_account", "savings_account_id", cashierId, currencyCode);
        final String clientSql = """
                SELECT COUNT(*) FROM m_client_transaction tx
                JOIN m_cashiers c ON c.id = ?
                JOIN m_appuser u ON u.id = tx.created_by AND u.staff_id = c.staff_id
                JOIN m_payment_detail pd ON pd.id = tx.payment_detail_id
                JOIN m_payment_type pt ON pt.id = pd.payment_type_id
                WHERE tx.cashier_id IS NULL AND tx.currency_code = ? AND tx.is_reversed = false
                  AND pt.is_cash_payment = true AND tx.transaction_date >= c.start_date
                  AND (c.end_date IS NULL OR tx.transaction_date <= c.end_date)
                """;
        count += jdbcTemplate.queryForObject(clientSql, Integer.class, cashierId, currencyCode);
        return count;
    }

    private int candidateCount(String table, String accountTable, String accountColumn, Long cashierId, String currencyCode) {
        final String sql = "SELECT COUNT(*) FROM " + table + " tx JOIN m_cashiers c ON c.id = ? "
                + "JOIN m_appuser u ON u.id = tx.created_by AND u.staff_id = c.staff_id "
                + "JOIN " + accountTable + " account_ ON account_.id = tx." + accountColumn + " "
                + "JOIN m_payment_detail pd ON pd.id = tx.payment_detail_id "
                + "JOIN m_payment_type pt ON pt.id = pd.payment_type_id "
                + "WHERE tx.cashier_id IS NULL AND account_.currency_code = ? AND tx.is_reversed = false "
                + "AND pt.is_cash_payment = true AND tx.transaction_date >= c.start_date "
                + "AND (c.end_date IS NULL OR tx.transaction_date <= c.end_date)";
        return jdbcTemplate.queryForObject(sql, Integer.class, cashierId, currencyCode);
    }

    private record Session(LocalDate startDate, LocalDate endDate, BigDecimal openingCash) {
    }
}
