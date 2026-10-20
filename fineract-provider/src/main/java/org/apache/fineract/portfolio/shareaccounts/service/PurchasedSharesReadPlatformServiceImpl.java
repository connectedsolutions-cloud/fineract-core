/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
package org.apache.fineract.portfolio.shareaccounts.service;

import java.math.BigDecimal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.Collection;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.infrastructure.core.domain.JdbcSupport;
import org.apache.fineract.portfolio.shareaccounts.data.ShareAccountTransactionData;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

@RequiredArgsConstructor
public class PurchasedSharesReadPlatformServiceImpl implements PurchasedSharesReadPlatformService {

    private final JdbcTemplate jdbcTemplate;

    @Override
    public Collection<ShareAccountTransactionData> retrievePurchasedShares(Long accountId) {
        PurchasedSharesDataRowMapper mapper = new PurchasedSharesDataRowMapper();
        final String sql = "select " + mapper.schema() + " where saps.account_id=? and saps.is_active = true";
        return this.jdbcTemplate.query(sql, mapper, new Object[] { accountId }); // NOSONAR
    }

    private static final class PurchasedSharesDataRowMapper implements RowMapper<ShareAccountTransactionData> {

        private final String schema;

        PurchasedSharesDataRowMapper() {
            StringBuilder buff = new StringBuilder()
                    .append("saps.id, saps.account_id, saps.transaction_date, saps.total_shares, saps.unit_price, ")
                    .append("saps.status_enum, saps.type_enum, saps.amount, saps.charge_amount as chargeamount, ")
                    .append("saps.amount_paid as amountPaid, pt.value as paymentTypeName, pd.check_number as checkNumber, ")
                    .append("pd.bank_number as bankNumber, pd.account_number as accountNumber, pd.receipt_number as receiptNumber, ")
                    .append("saps.cashier_transaction_id as cashierTransactionId ")
                    .append("from m_share_account_transactions saps ")
                    .append("left join m_payment_detail pd on pd.id = saps.payment_detail_id ")
                    .append("left join m_payment_type pt on pt.id = pd.payment_type_id ");
            schema = buff.toString();
        }

        @Override
        public ShareAccountTransactionData mapRow(ResultSet rs, int rowNum) throws SQLException {
            final Long id = rs.getLong("id");
            final Long accountId = rs.getLong("account_id");
            final LocalDate purchasedDate = rs.getDate("transaction_date").toLocalDate();
            final Long numberOfShares = JdbcSupport.getLong(rs, "total_shares");
            final BigDecimal purchasedPrice = rs.getBigDecimal("unit_price");
            final Integer status = rs.getInt("status_enum");
            final EnumOptionData statusEnum = SharesEnumerations.purchasedSharesEnum(status);
            final Integer type = rs.getInt("type_enum");
            final EnumOptionData typeEnum = SharesEnumerations.purchasedSharesEnum(type);
            final BigDecimal amount = JdbcSupport.getBigDecimalDefaultToZeroIfNull(rs, "amount");
            final BigDecimal chargeAmount = JdbcSupport.getBigDecimalDefaultToZeroIfNull(rs, "chargeamount");
            final BigDecimal amountPaid = JdbcSupport.getBigDecimalDefaultToZeroIfNull(rs, "amountPaid");
            final String paymentTypeName = rs.getString("paymentTypeName");
            final String checkNumber = rs.getString("checkNumber");
            final String bankNumber = rs.getString("bankNumber");
            final String accountNumber = rs.getString("accountNumber");
            final String receiptNumber = rs.getString("receiptNumber");
            final Long cashierTransactionId = JdbcSupport.getLong(rs, "cashierTransactionId");

            return new ShareAccountTransactionData(id, accountId, purchasedDate, numberOfShares, purchasedPrice, statusEnum, typeEnum,
                    amount, chargeAmount, amountPaid, paymentTypeName, checkNumber, bankNumber, accountNumber, receiptNumber,
                    cashierTransactionId);
        }

        public String schema() {
            return this.schema;
        }
    }
}
