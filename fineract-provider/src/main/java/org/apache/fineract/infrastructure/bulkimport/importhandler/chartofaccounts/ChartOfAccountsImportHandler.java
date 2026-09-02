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
package org.apache.fineract.infrastructure.bulkimport.importhandler.chartofaccounts;

import com.google.gson.GsonBuilder;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import org.apache.fineract.accounting.glaccount.data.GLAccountData;
import org.apache.fineract.accounting.glaccount.domain.GLAccount;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepository;
import org.apache.fineract.accounting.glaccount.domain.GLAccountRepositoryWrapper;
import org.apache.fineract.accounting.glaccount.domain.GLAccountType;
import org.apache.fineract.accounting.glaccount.domain.GLAccountUsage;
import org.apache.fineract.accounting.glaccount.exception.GLAccountNotFoundException;
import org.apache.fineract.accounting.journalentry.data.CreditDebit;
import org.apache.fineract.accounting.journalentry.data.JournalEntryData;
import org.apache.fineract.commands.domain.CommandWrapper;
import org.apache.fineract.commands.service.CommandWrapperBuilder;
import org.apache.fineract.commands.service.PortfolioCommandSourceWritePlatformService;
import org.apache.fineract.infrastructure.bulkimport.constants.ChartOfAcountsConstants;
import org.apache.fineract.infrastructure.bulkimport.constants.TemplatePopulateImportConstants;
import org.apache.fineract.infrastructure.bulkimport.data.Count;
import org.apache.fineract.infrastructure.bulkimport.importhandler.ImportHandler;
import org.apache.fineract.infrastructure.bulkimport.importhandler.ImportHandlerUtils;
import org.apache.fineract.infrastructure.bulkimport.importhandler.helper.CodeValueDataIdSerializer;
import org.apache.fineract.infrastructure.bulkimport.importhandler.helper.CurrencyDateCodeSerializer;
import org.apache.fineract.infrastructure.bulkimport.importhandler.helper.DateSerializer;
import org.apache.fineract.infrastructure.bulkimport.importhandler.helper.EnumOptionDataIdSerializer;
import org.apache.fineract.infrastructure.codes.data.CodeValueData;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.EnumOptionData;
import org.apache.fineract.infrastructure.core.serialization.GoogleGsonSerializerHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.organisation.monetary.data.CurrencyData;
import org.apache.poi.ss.usermodel.Cell;
import org.apache.poi.ss.usermodel.IndexedColors;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.ss.usermodel.Workbook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class ChartOfAccountsImportHandler implements ImportHandler {

    private static final Logger LOG = LoggerFactory.getLogger(ChartOfAccountsImportHandler.class);

    private final PortfolioCommandSourceWritePlatformService commandsSourceWritePlatformService;
    private final GLAccountRepositoryWrapper glAccountRepository;
    private final GLAccountRepository glAccountRepositoryDirect;

    @Autowired
    public ChartOfAccountsImportHandler(final PortfolioCommandSourceWritePlatformService commandsSourceWritePlatformService,
            GLAccountRepositoryWrapper glAccountRepository, GLAccountRepository glAccountRepositoryDirect) {
        this.commandsSourceWritePlatformService = commandsSourceWritePlatformService;
        this.glAccountRepository = glAccountRepository;
        this.glAccountRepositoryDirect = glAccountRepositoryDirect;
    }

    @Override
    public Count process(final Workbook workbook, final String locale, final String dateFormat) {
        List<GLAccountData> glAccounts = new ArrayList<>();
        // for opening bal
        List<JournalEntryData> glTransactions = new ArrayList<>();
        List<CreditDebit> credits = new ArrayList<>();
        List<CreditDebit> debits = new ArrayList<>();
        Map<Integer, String> parentGlCodeByRowIndex = new HashMap<>();

        boolean flagForOpBal = readExcelFile(workbook, glAccounts, parentGlCodeByRowIndex);
        return importEntity(workbook, glAccounts, parentGlCodeByRowIndex, glTransactions, credits, debits, flagForOpBal, locale,
                dateFormat);
    }

    private boolean readExcelFile(final Workbook workbook, final List<GLAccountData> glAccounts,
            final Map<Integer, String> parentGlCodeByRowIndex) {
        Sheet chartOfAccountsSheet = workbook.getSheet(TemplatePopulateImportConstants.CHART_OF_ACCOUNTS_SHEET_NAME);
        Integer noOfEntries = ImportHandlerUtils.getNumberOfRows(chartOfAccountsSheet, TemplatePopulateImportConstants.FIRST_COLUMN_INDEX);
        boolean flagForOpBal = false;
        for (int rowIndex = 1; rowIndex <= noOfEntries; rowIndex++) {
            Row row;
            row = chartOfAccountsSheet.getRow(rowIndex);
            if (ImportHandlerUtils.isNotImported(row, ChartOfAcountsConstants.STATUS_COL)) {
                GLAccountData accountData = readGlAccounts(row);
                glAccounts.add(accountData);

                // Store parent GL code by row index for later resolution
                String parentGlCode = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.PARENT_ID_COL, row);
                if (parentGlCode != null && !parentGlCode.trim().isEmpty()) {
                    parentGlCodeByRowIndex.put(accountData.getRowIndex(), parentGlCode.trim());
                }

                if (ImportHandlerUtils.readAsString(ChartOfAcountsConstants.OFFICE_COL, row) != null) {
                    flagForOpBal = Boolean.TRUE;
                } else {
                    flagForOpBal = Boolean.FALSE;
                }
            }
        }

        return flagForOpBal;
    }

    private GLAccountData readGlAccounts(final Row row) {

        String accountType = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACCOUNT_TYPE_COL, row);
        LOG.debug("Reading GL account from row {}, accountType: {}", row.getRowNum(), accountType);
        EnumOptionData accountTypeEnum = GLAccountType.fromString(accountType);
        if (accountTypeEnum == null && accountType != null) {
            LOG.error("Invalid account type '{}' in row {}. Valid types are: ASSET, LIABILITY, EQUITY, INCOME, EXPENSE, ORDER_ACCOUNT",
                    accountType, row.getRowNum());
            throw new RuntimeException(
                    "Invalid account type: " + accountType + ". Valid types are: ASSET, LIABILITY, EQUITY, INCOME, EXPENSE, ORDER_ACCOUNT");
        }
        if (accountTypeEnum == null) {
            LOG.warn("Account type is null in row {}", row.getRowNum());
        } else {
            LOG.debug("Account type parsed successfully: {} (id: {})", accountType, accountTypeEnum.getId());
        }
        String accountName = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACCOUNT_NAME_COL, row);
        String usage = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACCOUNT_USAGE_COL, row);
        Long usageId = null;
        EnumOptionData usageEnum = null;
        if (usage != null && usage.equals(GLAccountUsage.DETAIL.toString())) {
            usageId = 1L;
            usageEnum = new EnumOptionData(usageId, null, null);
        } else if (usage != null && usage.equals(GLAccountUsage.HEADER.toString())) {
            usageId = 2L;
            usageEnum = new EnumOptionData(usageId, null, null);
        }
        Boolean manualEntriesAllowed = ImportHandlerUtils.readAsBoolean(ChartOfAcountsConstants.MANUAL_ENTRIES_ALLOWED_COL, row);
        // Parent GL code is read and stored separately in readExcelFile() - will be resolved to parentId in
        // importEntity()
        Long parentId = null; // Will be resolved in importEntity() based on parent GL code
        String glCode = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.GL_CODE_COL, row);
        Long tagId = null;
        CodeValueData tagIdCodeValueData = null;
        if (ImportHandlerUtils.readAsString(ChartOfAcountsConstants.TAG_ID_COL, row) != null
                && !ImportHandlerUtils.readAsString(ChartOfAcountsConstants.TAG_ID_COL, row).equals("0")) {
            tagId = Long.parseLong(Objects.requireNonNull(ImportHandlerUtils.readAsString(ChartOfAcountsConstants.TAG_ID_COL, row)));
            tagIdCodeValueData = new CodeValueData().setId(tagId);
        }
        String description = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.DESCRIPTION_COL, row);
        // Optional: Read accLevel and accLastLevel if columns exist in Excel template
        Integer accLevel = null;
        Integer accLastLevel = null;
        try {
            // First try reading as Integer (handles numeric formulas better)
            Integer accLevelInt = ImportHandlerUtils.readAsInt(ChartOfAcountsConstants.ACC_LEVEL_COL, row);
            if (accLevelInt != null) {
                accLevel = accLevelInt;
                LOG.debug("Read accLevel as integer from column {} (row {}): {}", ChartOfAcountsConstants.ACC_LEVEL_COL, row.getRowNum(),
                        accLevel);
            } else {
                LOG.debug("readAsInt returned null for accLevel at column {} (row {}), trying readAsString",
                        ChartOfAcountsConstants.ACC_LEVEL_COL, row.getRowNum());
                // Fallback to string parsing if readAsInt fails
                String accLevelStr = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACC_LEVEL_COL, row);
                LOG.debug("Reading accLevel from column {} (row {}): '{}'", ChartOfAcountsConstants.ACC_LEVEL_COL, row.getRowNum(),
                        accLevelStr);
                if (accLevelStr != null && !accLevelStr.isEmpty()) {
                    accLevel = Integer.parseInt(accLevelStr);
                    LOG.debug("Parsed accLevel value: {}", accLevel);
                } else {
                    LOG.debug("accLevel is null or empty for row {}", row.getRowNum());
                }
            }
        } catch (Exception e) {
            LOG.warn("Error reading accLevel from column {} in row {}: {}", ChartOfAcountsConstants.ACC_LEVEL_COL, row.getRowNum(),
                    e.getMessage(), e);
            // Column may not exist in template, ignore
        }
        try {
            String accLastLevelStr = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACC_LAST_LEVEL_COL, row);
            LOG.debug("Reading accLastLevel from column {} (row {}): '{}'", ChartOfAcountsConstants.ACC_LAST_LEVEL_COL, row.getRowNum(),
                    accLastLevelStr);
            if (accLastLevelStr != null && !accLastLevelStr.isEmpty()) {
                accLastLevel = Integer.parseInt(accLastLevelStr);
                LOG.debug("Parsed accLastLevel value: {}", accLastLevel);
            } else {
                LOG.debug("accLastLevel is null or empty for row {}", row.getRowNum());
            }
        } catch (Exception e) {
            LOG.warn("Error reading accLastLevel from column {} in row {}: {}", ChartOfAcountsConstants.ACC_LAST_LEVEL_COL, row.getRowNum(),
                    e.getMessage());
            // Column may not exist in template, ignore
        }
        GLAccountData accountData = new GLAccountData().setName(accountName).setParentId(parentId).setGlCode(glCode)
                .setManualEntriesAllowed(manualEntriesAllowed).setType(accountTypeEnum).setUsage(usageEnum).setDescription(description)
                .setTagId(tagIdCodeValueData).setRowIndex(row.getRowNum()).setAccLevel(accLevel).setAccLastLevel(accLastLevel);
        LOG.debug("Created GLAccountData for row {} - accLevel: {}, accLastLevel: {}", row.getRowNum(), accountData.getAccLevel(),
                accountData.getAccLastLevel());
        return accountData;
    }

    private Count importEntity(final Workbook workbook, final List<GLAccountData> glAccounts,
            final Map<Integer, String> parentGlCodeByRowIndex, final List<JournalEntryData> glTransactions, final List<CreditDebit> credits,
            final List<CreditDebit> debits, final boolean flagForOpBal, final String locale, final String dateFormat) {
        Sheet chartOfAccountsSheet = workbook.getSheet(TemplatePopulateImportConstants.CHART_OF_ACCOUNTS_SHEET_NAME);

        GsonBuilder gsonBuilder = GoogleGsonSerializerHelper.createGsonBuilder();
        gsonBuilder.registerTypeAdapter(EnumOptionData.class, new EnumOptionDataIdSerializer());
        gsonBuilder.registerTypeAdapter(CodeValueData.class, new CodeValueDataIdSerializer());
        gsonBuilder.registerTypeAdapter(LocalDate.class, new DateSerializer(dateFormat, locale));
        gsonBuilder.registerTypeAdapter(CurrencyData.class, new CurrencyDateCodeSerializer());
        int successCount = 0;
        int errorCount = 0;
        String errorMessage = "";

        if (glAccounts != null && !glAccounts.isEmpty()) {
            // Track processed GL codes to prevent duplicate processing
            Set<String> processedGlCodes = new HashSet<>();

            // Track newly created accounts by GL code to support parent lookups within same import
            Map<String, Long> createdAccountIdsByGlCode = new HashMap<>();

            for (GLAccountData glAccount : glAccounts) {
                String glCode = glAccount.getGlCode();

                // Skip if this GL code has already been processed in this import
                if (processedGlCodes.contains(glCode)) {
                    LOG.warn("Skipping duplicate GL code in import: row={}, glCode={}, name={}. Already processed.",
                            glAccount.getRowIndex(), glCode, glAccount.getName());
                    errorCount++;
                    errorMessage = "Duplicate GL code in import file: " + glCode;
                    ImportHandlerUtils.writeErrorMessage(chartOfAccountsSheet, glAccount.getRowIndex(), errorMessage,
                            ChartOfAcountsConstants.STATUS_COL);
                    continue;
                }

                // Check if account already exists in database to avoid unnecessary processing
                if (this.glAccountRepositoryDirect.findOneByGlCode(glCode).isPresent()) {
                    LOG.warn("Account with GL code {} already exists in database. Skipping row {} (name: {}).", glCode,
                            glAccount.getRowIndex(), glAccount.getName());
                    processedGlCodes.add(glCode); // Mark as processed to avoid duplicate attempts

                    // Store existing account ID in the map for potential parent lookups
                    GLAccount existingAccount = this.glAccountRepositoryDirect.findOneByGlCode(glCode).orElse(null);
                    if (existingAccount != null) {
                        createdAccountIdsByGlCode.put(glCode, existingAccount.getId());
                    }

                    successCount++; // Count as success since account exists
                    Cell statusCell = chartOfAccountsSheet.getRow(glAccount.getRowIndex()).createCell(ChartOfAcountsConstants.STATUS_COL);
                    statusCell.setCellValue(TemplatePopulateImportConstants.STATUS_CELL_IMPORTED);
                    statusCell.setCellStyle(ImportHandlerUtils.getCellStyle(workbook, IndexedColors.LIGHT_GREEN));
                    continue;
                }

                // Resolve parent GL code to parent ID if parent GL code exists
                String parentGlCode = parentGlCodeByRowIndex.get(glAccount.getRowIndex());
                if (parentGlCode != null && !parentGlCode.trim().isEmpty()) {
                    Long resolvedParentId = null;

                    // First check if parent was created earlier in this import
                    if (createdAccountIdsByGlCode.containsKey(parentGlCode)) {
                        resolvedParentId = createdAccountIdsByGlCode.get(parentGlCode);
                        LOG.debug("Found parent account in same import: parentGlCode={}, parentId={}", parentGlCode, resolvedParentId);
                    } else {
                        // Look up parent in database
                        var parentAccountOpt = this.glAccountRepositoryDirect.findOneByGlCode(parentGlCode);
                        if (parentAccountOpt.isPresent()) {
                            resolvedParentId = parentAccountOpt.get().getId();
                            LOG.debug("Found parent account in database: parentGlCode={}, parentId={}", parentGlCode, resolvedParentId);
                            // Store in map for potential future lookups
                            createdAccountIdsByGlCode.put(parentGlCode, resolvedParentId);
                        } else {
                            String error = String.format(
                                    "Parent account with GL code '%s' not found for account at row %d (name: %s, glCode: %s). Parent must exist in database or appear earlier in the import file.",
                                    parentGlCode, glAccount.getRowIndex(), glAccount.getName(), glCode);
                            LOG.error(error);
                            errorCount++;
                            errorMessage = "Parent account not found: " + parentGlCode;
                            ImportHandlerUtils.writeErrorMessage(chartOfAccountsSheet, glAccount.getRowIndex(), errorMessage,
                                    ChartOfAcountsConstants.STATUS_COL);
                            continue;
                        }
                    }

                    // Set the resolved parent ID on the account data
                    glAccount.setParentId(resolvedParentId);
                }

                try {
                    // Mark as being processed
                    processedGlCodes.add(glCode);

                    // Log account details for debugging
                    LOG.debug("Processing account: row={}, name={}, glCode={}, parentId={}", glAccount.getRowIndex(), glAccount.getName(),
                            glCode, glAccount.getParentId());

                    String payload = gsonBuilder.create().toJson(glAccount);
                    LOG.debug("JSON payload for row {}: accLevel={}, accLastLevel={}", glAccount.getRowIndex(), glAccount.getAccLevel(),
                            glAccount.getAccLastLevel());
                    LOG.debug("Full JSON payload: {}", payload);
                    final CommandWrapper commandRequest = new CommandWrapperBuilder() //
                            .createGLAccount() //
                            .withJson(payload) //
                            .build(); //
                    CommandProcessingResult result = commandsSourceWritePlatformService.logCommandSource(commandRequest);

                    // Track successfully created account by GL code for parent lookups
                    Long createdAccountId = result.getResourceId();
                    if (createdAccountId != null) {
                        createdAccountIdsByGlCode.put(glCode, createdAccountId);
                        LOG.debug("Tracked newly created account: glCode={}, accountId={}", glCode, createdAccountId);
                    } else {
                        LOG.warn("Could not get resourceId from command result for account: glCode={}, name={}. Parent lookups may fail.",
                                glCode, glAccount.getName());
                    }

                    successCount++;

                    Cell statusCell = chartOfAccountsSheet.getRow(glAccount.getRowIndex()).createCell(ChartOfAcountsConstants.STATUS_COL);
                    statusCell.setCellValue(TemplatePopulateImportConstants.STATUS_CELL_IMPORTED);
                    statusCell.setCellStyle(ImportHandlerUtils.getCellStyle(workbook, IndexedColors.LIGHT_GREEN));

                    LOG.info("Successfully imported account: row={}, name={}, glCode={}", glAccount.getRowIndex(), glAccount.getName(),
                            glCode);
                } catch (RuntimeException ex) {
                    // Check if it's a duplicate GL code error
                    String errorMsg = ex.getMessage();
                    if (errorMsg != null && (errorMsg.contains("duplicate key") || errorMsg.contains("acc_gl_code")
                            || errorMsg.contains("GLAccountDuplicateException") || errorMsg.contains("already present"))) {
                        LOG.warn("Account with GL code {} already exists (duplicate key error). Skipping row {} (name: {}). Error: {}",
                                glCode, glAccount.getRowIndex(), glAccount.getName(), errorMsg);
                        // Don't increment error count for duplicates - account already exists
                        successCount++;
                        Cell statusCell = chartOfAccountsSheet.getRow(glAccount.getRowIndex())
                                .createCell(ChartOfAcountsConstants.STATUS_COL);
                        statusCell.setCellValue(TemplatePopulateImportConstants.STATUS_CELL_IMPORTED);
                        statusCell.setCellStyle(ImportHandlerUtils.getCellStyle(workbook, IndexedColors.LIGHT_GREEN));
                    } else {
                        errorCount++;
                        String detailedError = String.format(
                                "Failed to import account at row %d (name: %s, glCode: %s, parentId: %s). Error: %s",
                                glAccount.getRowIndex(), glAccount.getName(), glCode, glAccount.getParentId(), errorMsg);
                        LOG.error("Problem occurred in importEntity function. {}", detailedError, ex);
                        errorMessage = ImportHandlerUtils.getErrorMessage(ex);
                        ImportHandlerUtils.writeErrorMessage(chartOfAccountsSheet, glAccount.getRowIndex(), errorMessage,
                                ChartOfAcountsConstants.STATUS_COL);
                        // Remove from processed set so it can be retried if needed
                        processedGlCodes.remove(glCode);
                    }
                }
            }

            LOG.info("Import completed: {} successful, {} failed", successCount, errorCount);
            if (flagForOpBal) {
                try {
                    readExcelFileForOpBal(workbook, glTransactions, credits, debits, locale, dateFormat);
                    JournalEntryData transaction = glTransactions.get(glTransactions.size() - 1);
                    String payload = gsonBuilder.create().toJson(transaction);

                    final CommandWrapper commandRequest = new CommandWrapperBuilder().defineOpeningBalanceForJournalEntry()
                            .withJson(payload).build();
                    commandsSourceWritePlatformService.logCommandSource(commandRequest);
                    successCount++;
                    Cell statusCell = chartOfAccountsSheet.getRow(1).createCell(ChartOfAcountsConstants.STATUS_COL);
                    statusCell.setCellValue(TemplatePopulateImportConstants.STATUS_CELL_IMPORTED);
                    statusCell.setCellStyle(ImportHandlerUtils.getCellStyle(workbook, IndexedColors.LIGHT_GREEN));
                } catch (RuntimeException ex) {
                    errorCount++;
                    LOG.error("Problem occurred in importEntity function", ex);
                    errorMessage = ImportHandlerUtils.getErrorMessage(ex);
                    ImportHandlerUtils.writeErrorMessage(chartOfAccountsSheet, 1, errorMessage, ChartOfAcountsConstants.STATUS_COL);
                }
            }
            chartOfAccountsSheet.setColumnWidth(ChartOfAcountsConstants.STATUS_COL, TemplatePopulateImportConstants.SMALL_COL_SIZE);
            ImportHandlerUtils.writeString(ChartOfAcountsConstants.STATUS_COL,
                    chartOfAccountsSheet.getRow(TemplatePopulateImportConstants.ROWHEADER_INDEX),
                    TemplatePopulateImportConstants.STATUS_COLUMN_HEADER);
            return Count.instance(successCount, errorCount);
        }

        chartOfAccountsSheet.setColumnWidth(ChartOfAcountsConstants.STATUS_COL, TemplatePopulateImportConstants.SMALL_COL_SIZE);
        ImportHandlerUtils.writeString(ChartOfAcountsConstants.STATUS_COL,
                chartOfAccountsSheet.getRow(TemplatePopulateImportConstants.ROWHEADER_INDEX),
                TemplatePopulateImportConstants.STATUS_COLUMN_HEADER);
        return Count.instance(successCount, errorCount);

    }

    // for opening balance
    private void readExcelFileForOpBal(final Workbook workbook, final List<JournalEntryData> glTransactions,
            final List<CreditDebit> credits, final List<CreditDebit> debits, final String locale, final String dateFormat) {

        Sheet chartOfAccountsSheet = workbook.getSheet(TemplatePopulateImportConstants.CHART_OF_ACCOUNTS_SHEET_NAME);
        Integer noOfEntries = ImportHandlerUtils.getNumberOfRows(chartOfAccountsSheet, TemplatePopulateImportConstants.FIRST_COLUMN_INDEX);
        for (int rowIndex = 1; rowIndex <= noOfEntries; rowIndex++) {
            Row row;
            row = chartOfAccountsSheet.getRow(rowIndex);

            //
            JournalEntryData journalEntry;
            journalEntry = readAddJournalEntries(row, credits, debits, locale, dateFormat);
            glTransactions.add(journalEntry);
        }

    }

    // for opening balance
    private JournalEntryData readAddJournalEntries(final Row row, final List<CreditDebit> credits, final List<CreditDebit> debits,
            final String locale, String dateFormat) {
        LocalDate transactionDate = DateUtils.getBusinessLocalDate();

        Long officeId = ImportHandlerUtils.readAsLong(ChartOfAcountsConstants.OFFICE_COL_ID, row);

        String currencyCode = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.CURRENCY_CODE, row);
        String accountToBeDebitedCredited = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.ACCOUNT_NAME_COL, row);
        String glCode = ImportHandlerUtils.readAsString(ChartOfAcountsConstants.GL_CODE_COL, row);
        GLAccount glAccount = this.glAccountRepository.findOneByGlCodeWithNotFoundDetection(glCode);
        Long glAccountIdToDebitedCredited = glAccount.getId();
        if (glAccountIdToDebitedCredited == null) {
            throw new GLAccountNotFoundException("Account does not exist");
        }

        // String credit =
        // readAsString(JournalEntryConstants.GL_ACCOUNT_ID_CREDIT_COL, row);
        // String debit =
        // readAsString(JournalEntryConstants.GL_ACCOUNT_ID_DEBIT_COL, row);

        if (accountToBeDebitedCredited != null) {
            if (ImportHandlerUtils.readAsLong(ChartOfAcountsConstants.CREDIT_AMOUNT, row) != null) {
                credits.add(new CreditDebit(glAccountIdToDebitedCredited,
                        BigDecimal.valueOf(ImportHandlerUtils.readAsLong(ChartOfAcountsConstants.CREDIT_AMOUNT, row))));

            } else if (ImportHandlerUtils.readAsLong(ChartOfAcountsConstants.DEBIT_AMOUNT, row) != null) {
                debits.add(new CreditDebit(glAccountIdToDebitedCredited,
                        BigDecimal.valueOf(ImportHandlerUtils.readAsLong(ChartOfAcountsConstants.DEBIT_AMOUNT, row))));
            }
        }

        return JournalEntryData.importInstance1(officeId, transactionDate, currencyCode, credits, debits, locale, dateFormat);

    }

}
