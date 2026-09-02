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
package org.apache.fineract.cob.service;

import static org.springframework.transaction.TransactionDefinition.PROPAGATION_REQUIRES_NEW;

import com.google.common.collect.Lists;
import com.google.gson.Gson;
import edu.umd.cs.findbugs.annotations.SuppressFBWarnings;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.cob.conditions.LoanCOBEnabledCondition;
import org.apache.fineract.cob.data.COBIdAndLastClosedBusinessDate;
import org.apache.fineract.cob.domain.LoanAccountLock;
import org.apache.fineract.cob.domain.LoanAccountLockRepository;
import org.apache.fineract.cob.domain.LockOwner;
import org.apache.fineract.cob.exceptions.AccountLockCannotBeOverruledException;
import org.apache.fineract.cob.loan.LoanCOBConstant;
import org.apache.fineract.cob.loan.RetrieveLoanIdService;
import org.apache.fineract.infrastructure.businessdate.domain.BusinessDateType;
import org.apache.fineract.infrastructure.core.api.JsonCommand;
import org.apache.fineract.infrastructure.core.config.FineractProperties;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.exception.PlatformInternalServerException;
import org.apache.fineract.infrastructure.core.exception.PlatformRequestBodyItemLimitValidationException;
import org.apache.fineract.infrastructure.core.serialization.GoogleGsonSerializerHelper;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.core.service.ThreadLocalContextUtil;
import org.apache.fineract.infrastructure.jobs.data.JobParameterDTO;
import org.apache.fineract.infrastructure.jobs.domain.CustomJobParameterRepository;
import org.apache.fineract.infrastructure.jobs.exception.JobNotFoundException;
import org.apache.fineract.infrastructure.jobs.service.InlineExecutorService;
import org.apache.fineract.infrastructure.security.service.PlatformSecurityContext;
import org.apache.fineract.infrastructure.springbatch.SpringBatchJobConstants;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepository;
import org.springframework.batch.core.BatchStatus;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.JobExecution;
import org.springframework.batch.core.JobParameter;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.configuration.JobLocator;
import org.springframework.batch.core.explore.JobExplorer;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.batch.core.launch.NoSuchJobException;
import org.springframework.context.annotation.Conditional;
import org.springframework.lang.NonNull;
import org.springframework.stereotype.Service;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionCallbackWithoutResult;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Service for executing inline (manual) COB jobs for specific loans.
 *
 * IMPORTANT: This service is ONLY used for inline COB execution (manual API calls), NOT for regular scheduled COB.
 * Regular scheduled COB uses LoanCOBManagerConfiguration/LoanCOBPartitioner which use database queries that exclude
 * simulated loans via loan.isSimulation = false condition.
 *
 * For inline COB, we allow processing simulated loans when they are explicitly included in the loanIds list, enabling
 * simulation mode functionality while ensuring regular COB never processes simulated loans.
 */
@Service
@Slf4j
@RequiredArgsConstructor
@Conditional(LoanCOBEnabledCondition.class)
public class InlineLoanCOBExecutorServiceImpl implements InlineExecutorService<Long> {

    private static final String JOB_EXECUTION_FAILED_MESSAGE = "Job execution failed for job with name: ";
    private final LoanAccountLockRepository loanAccountLockRepository;
    private final InlineLoanCOBExecutionDataParser dataParser;
    private final JobLauncher jobLauncher;
    private final JobLocator jobLocator;
    private final JobExplorer jobExplorer;
    private final TransactionTemplate transactionTemplate;
    private final CustomJobParameterRepository customJobParameterRepository;
    private final PlatformSecurityContext context;
    private final RetrieveLoanIdService retrieveLoanIdService;
    private final FineractProperties fineractProperties;
    private final LoanRepository loanRepository;

    private final Gson gson = GoogleGsonSerializerHelper.createSimpleGson();

    @Override
    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    public CommandProcessingResult executeInlineJob(JsonCommand command, String jobName) throws AccountLockCannotBeOverruledException {
        List<Long> loanIds = dataParser.parseExecution(command);
        validateLoanIdsListSize(loanIds);
        execute(loanIds, jobName);
        return new CommandProcessingResultBuilder().withCommandId(command.commandId()).build();
    }

    @Override
    public void execute(List<Long> loanIds, String jobName) {
        LocalDate cobBusinessDate = ThreadLocalContextUtil.getBusinessDateByType(BusinessDateType.COB_DATE);
        LocalDate actualCobBusinessDate = cobBusinessDate;
        boolean isSimulationCOB = false;

        log.info("Starting inline COB execution for {} loans, global COB date: {}", loanIds.size(), cobBusinessDate);

        // Determine if this is a simulation COB by checking if ANY loan in the list is simulated
        for (Long loanId : loanIds) {
            Optional<Loan> loanOptional = loanRepository.findById(loanId);
            if (loanOptional.isPresent()) {
                Loan loan = loanOptional.get();
                log.info("Checking loan [{}]: isSimulation={}, simulatedDate={}, lastClosedBusinessDate={}", loanId, loan.getIsSimulation(),
                        loan.getSimulatedDate(), loan.getLastClosedBusinessDate());
                if (Boolean.TRUE.equals(loan.getIsSimulation()) && loan.getSimulatedDate() != null) {
                    isSimulationCOB = true;
                    actualCobBusinessDate = loan.getSimulatedDate();
                    log.info("Detected SIMULATION COB: Using simulated date [{}] instead of global COB date [{}] for loan [{}]",
                            actualCobBusinessDate, cobBusinessDate, loanId);
                    break; // Use the first simulated loan's date (assuming single loan per batch for simulation)
                }
            }
        }

        if (isSimulationCOB) {
            log.info("Executing SIMULATION COB - simulated loans will be included in processing");
        } else {
            log.info("Executing NORMAL inline COB - only non-simulated loans will be processed");
        }

        List<COBIdAndLastClosedBusinessDate> loansToBeProcessed = getLoansToBeProcessed(loanIds, actualCobBusinessDate, isSimulationCOB);
        log.info("Found {} loans to be processed (target date: {})", loansToBeProcessed.size(), actualCobBusinessDate);

        // For simulation COB, calculate the proper baseline date for day-by-day processing
        LocalDate executingBusinessDate;
        LocalDate baselineDate = null;
        if (isSimulationCOB) {
            baselineDate = getSimulationBaselineDate(loanIds, actualCobBusinessDate);
            executingBusinessDate = baselineDate.plusDays(1);
            log.info("Simulation COB: Calculated baseline date: {}, starting day-by-day execution from: {} to: {}", baselineDate,
                    executingBusinessDate, actualCobBusinessDate);
        } else {
            executingBusinessDate = getOldestCOBBusinessDate(loansToBeProcessed).plusDays(1);
            log.info("Oldest COB business date: {}, starting execution from: {}", getOldestCOBBusinessDate(loansToBeProcessed),
                    executingBusinessDate);
        }

        if (!loansToBeProcessed.isEmpty()) {
            long totalDays = isSimulationCOB && baselineDate != null ? actualCobBusinessDate.toEpochDay() - baselineDate.toEpochDay() : 0;
            long currentDay = 0;

            while (!DateUtils.isAfter(executingBusinessDate, actualCobBusinessDate)) {
                currentDay++;
                // For simulation COB, always process all loan IDs day-by-day
                // For normal COB, filter based on lastClosedBusinessDate
                List<Long> loanIdsToProcess;
                if (isSimulationCOB) {
                    // In simulation mode, process all loans each day (loan state will be refreshed from DB in each
                    // batch job)
                    loanIdsToProcess = loanIds;
                    log.info("Executing COB for {} loans on date: {} (day {}/{} of simulation - processing all loans)",
                            loanIdsToProcess.size(), executingBusinessDate, currentDay, totalDays);
                } else {
                    loanIdsToProcess = getLoanIdsToBeProcessed(loansToBeProcessed, executingBusinessDate);
                    log.info("Executing COB for {} loans on date: {}", loanIdsToProcess.size(), executingBusinessDate);
                }

                if (!loanIdsToProcess.isEmpty()) {
                    // The executingBusinessDate is passed as the businessDate parameter to the batch job
                    // InlineLoanCOBBuildExecutionContextTasklet will use this as the simulated date for ThreadLocal
                    execute(loanIdsToProcess, jobName, executingBusinessDate);
                } else {
                    log.warn("No loans to process on date: {}", executingBusinessDate);
                }

                executingBusinessDate = executingBusinessDate.plusDays(1);
            }
            if (isSimulationCOB) {
                log.info("Completed day-by-day simulation COB processing: processed {} days from baseline {} to simulated date {}",
                        totalDays, baselineDate, actualCobBusinessDate);
            }
        } else {
            log.warn("No loans to be processed for COB execution");
        }
    }

    private List<Long> getLoanIdsToBeProcessed(List<COBIdAndLastClosedBusinessDate> loansToBeProcessed, LocalDate executingBusinessDate) {
        List<Long> loanIdsToBeProcessed = new ArrayList<>();
        loansToBeProcessed.forEach(loan -> {
            if (loan.getLastClosedBusinessDate() != null) {
                if (DateUtils.isBefore(loan.getLastClosedBusinessDate(), executingBusinessDate)) {
                    loanIdsToBeProcessed.add(loan.getId());
                }
            } else {
                loanIdsToBeProcessed.add(loan.getId());
            }
        });
        return loanIdsToBeProcessed;
    }

    @SuppressFBWarnings("SLF4J_SIGN_ONLY_FORMAT")
    private void execute(List<Long> loanIds, String jobName, LocalDate businessDate) {
        // For simulation COB, businessDate is already set to the current processing day in the day-by-day loop
        // We should NOT overwrite it with the loan's final simulatedDate - that would cause all days to use the final
        // date!
        // The businessDate parameter is the correct date to use for this day's processing
        LocalDate actualBusinessDate = businessDate;

        // Note: ThreadLocal simulated date is set in InlineLoanCOBBuildExecutionContextTasklet using the businessDate
        // parameter
        // We don't set it here to avoid overwriting with the final simulated date

        lockLoanAccounts(loanIds, actualBusinessDate);
        Job inlineLoanCOBJob;
        try {
            inlineLoanCOBJob = jobLocator.getJob(jobName);
        } catch (NoSuchJobException e) {
            throw new JobNotFoundException(jobName, e);
        }
        JobParameters jobParameters = new JobParametersBuilder(jobExplorer).getNextJobParameters(inlineLoanCOBJob)
                .addJobParameters(new JobParameters(getJobParametersMap(loanIds, actualBusinessDate))).toJobParameters();
        JobExecution jobExecution;
        try {
            jobExecution = jobLauncher.run(inlineLoanCOBJob, jobParameters);
        } catch (Exception e) {
            log.error("{}{}", JOB_EXECUTION_FAILED_MESSAGE, jobName, e);
            throw new PlatformInternalServerException("error.msg.sheduler.job.execution.failed", JOB_EXECUTION_FAILED_MESSAGE, jobName, e);
        }
        if (!BatchStatus.COMPLETED.equals(jobExecution.getStatus())) {
            log.error("{}{}", JOB_EXECUTION_FAILED_MESSAGE, jobName);
            throw new PlatformInternalServerException("error.msg.sheduler.job.execution.failed", JOB_EXECUTION_FAILED_MESSAGE, jobName);
        }
        // Clear ThreadLocal simulated date after processing
        ThreadLocalContextUtil.clearLoanSimulatedDate();
    }

    private LocalDate getOldestCOBBusinessDate(List<COBIdAndLastClosedBusinessDate> loans) {
        COBIdAndLastClosedBusinessDate oldestLoan = loans.stream().min(Comparator
                .comparing(COBIdAndLastClosedBusinessDate::getLastClosedBusinessDate, Comparator.nullsLast(Comparator.naturalOrder())))
                .orElse(null);
        return oldestLoan != null && oldestLoan.getLastClosedBusinessDate() != null ? oldestLoan.getLastClosedBusinessDate()
                : ThreadLocalContextUtil.getBusinessDateByType(BusinessDateType.COB_DATE).minusDays(1);
    }

    /**
     * Calculate the baseline date for simulation COB processing. The baseline is the oldest of: accruedTill,
     * disbursementDate, lastClosedBusinessDate, simulationStartLastClosedBusinessDate. This ensures we process from the
     * earliest relevant date up to the simulated date.
     */
    private LocalDate getSimulationBaselineDate(List<Long> loanIds, LocalDate simulatedDate) {
        LocalDate oldestBaseline = null;

        for (Long loanId : loanIds) {
            Optional<Loan> loanOptional = loanRepository.findById(loanId);
            if (loanOptional.isPresent()) {
                Loan loan = loanOptional.get();
                if (Boolean.TRUE.equals(loan.getIsSimulation()) && loan.getSimulatedDate() != null) {
                    // Get all potential baseline dates
                    LocalDate accruedTill = loan.getAccruedTill();
                    LocalDate disbursementDate = loan.getDisbursementDate();
                    LocalDate lastClosedBusinessDate = loan.getLastClosedBusinessDate();
                    LocalDate simulationStartLastClosedBusinessDate = loan.getSimulationStartLastClosedBusinessDate();

                    // Find the oldest non-null date among all potential baselines
                    LocalDate loanBaseline = null;
                    if (simulationStartLastClosedBusinessDate != null) {
                        loanBaseline = simulationStartLastClosedBusinessDate;
                    }
                    if (accruedTill != null && (loanBaseline == null || DateUtils.isBefore(accruedTill, loanBaseline))) {
                        loanBaseline = accruedTill;
                    }
                    if (disbursementDate != null && (loanBaseline == null || DateUtils.isBefore(disbursementDate, loanBaseline))) {
                        loanBaseline = disbursementDate;
                    }
                    if (lastClosedBusinessDate != null
                            && (loanBaseline == null || DateUtils.isBefore(lastClosedBusinessDate, loanBaseline))) {
                        loanBaseline = lastClosedBusinessDate;
                    }

                    // Update the overall oldest baseline
                    if (loanBaseline != null) {
                        if (oldestBaseline == null || DateUtils.isBefore(loanBaseline, oldestBaseline)) {
                            oldestBaseline = loanBaseline;
                        }
                    }

                    log.info(
                            "Loan [{}] baseline calculation: accruedTill={}, disbursementDate={}, lastClosedBusinessDate={}, "
                                    + "simulationStartLastClosedBusinessDate={}, calculatedBaseline={}",
                            loanId, accruedTill, disbursementDate, lastClosedBusinessDate, simulationStartLastClosedBusinessDate,
                            loanBaseline);
                }
            }
        }

        // If no baseline found, use simulated date minus 1 day as fallback
        if (oldestBaseline == null) {
            oldestBaseline = simulatedDate.minusDays(1);
            log.warn("No baseline date found for simulated loans, using simulatedDate - 1 day: {}", oldestBaseline);
        }

        log.info("Simulation baseline date determined: {} (will process from {} to {})", oldestBaseline, oldestBaseline.plusDays(1),
                simulatedDate);

        return oldestBaseline;
    }

    /**
     * Get loans to be processed for inline COB execution.
     *
     * NOTE: This method is ONLY used for inline COB (manual execution via API), NOT for regular scheduled COB. Regular
     * scheduled COB uses different services/queries that properly exclude simulated loans via loan.isSimulation = false
     * condition in the database queries.
     *
     * @param loanIds
     *            List of loan IDs to process
     * @param cobBusinessDate
     *            The COB business date to use (may be simulated date for simulation COB)
     * @param isSimulationCOB
     *            Flag indicating if this is a simulation COB execution
     * @return List of loans to be processed
     */
    private List<COBIdAndLastClosedBusinessDate> getLoansToBeProcessed(List<Long> loanIds, LocalDate cobBusinessDate,
            boolean isSimulationCOB) {
        List<COBIdAndLastClosedBusinessDate> loanIdAndLastClosedBusinessDates = new ArrayList<>();
        List<List<Long>> partitions = Lists.partition(loanIds, fineractProperties.getQuery().getInClauseParameterSizeLimit());
        partitions.forEach(partition -> loanIdAndLastClosedBusinessDates
                .addAll(retrieveLoanIdService.retrieveLoanIdsBehindDateOrNull(cobBusinessDate, partition)));

        // IMPORTANT: Only add simulated loans if this is a SIMULATION COB execution.
        // Regular scheduled COB will never call this method, and the queries used by regular COB
        // already exclude simulated loans via loan.isSimulation = false condition.
        // For normal inline COB (non-simulation), we also exclude simulated loans to maintain safety.
        if (isSimulationCOB) {
            log.info("Simulation COB detected - including simulated loans in processing list");
            for (Long loanId : loanIds) {
                Optional<Loan> loanOptional = loanRepository.findById(loanId);
                if (loanOptional.isPresent()) {
                    Loan loan = loanOptional.get();
                    if (Boolean.TRUE.equals(loan.getIsSimulation()) && loan.getSimulatedDate() != null) {
                        // For simulated loans, use simulationStartLastClosedBusinessDate as baseline if available,
                        // otherwise use lastClosedBusinessDate or disbursementDate
                        LocalDate baselineDate = loan.getSimulationStartLastClosedBusinessDate();
                        if (baselineDate == null) {
                            baselineDate = loan.getLastClosedBusinessDate();
                            if (baselineDate == null) {
                                baselineDate = loan.getDisbursementDate();
                            }
                        }

                        // Check if loan needs processing (baseline date is before simulated date)
                        if (baselineDate == null || DateUtils.isBefore(baselineDate, loan.getSimulatedDate())) {
                            // Use the actual lastClosedBusinessDate for the COB processing
                            LocalDate lastClosedDate = loan.getLastClosedBusinessDate();

                            // Create a COBIdAndLastClosedBusinessDate instance for the simulated loan
                            final Long id = loanId;
                            final LocalDate lastClosed = lastClosedDate;
                            COBIdAndLastClosedBusinessDate simulatedLoan = new COBIdAndLastClosedBusinessDate() {

                                @Override
                                public Long getId() {
                                    return id;
                                }

                                @Override
                                public LocalDate getLastClosedBusinessDate() {
                                    return lastClosed;
                                }
                            };
                            // Only add if not already in the list
                            boolean alreadyExists = loanIdAndLastClosedBusinessDates.stream().anyMatch(l -> l.getId().equals(loanId));
                            if (!alreadyExists) {
                                loanIdAndLastClosedBusinessDates.add(simulatedLoan);
                                log.info(
                                        "Added simulated loan [{}] to processing list (baselineDate={}, lastClosedBusinessDate={}, simulatedDate={})",
                                        loanId, baselineDate, lastClosedDate, loan.getSimulatedDate());
                            }
                        } else {
                            log.info("Simulated loan [{}] does not need processing (baselineDate={} >= simulatedDate={})", loanId,
                                    baselineDate, loan.getSimulatedDate());
                        }
                    }
                }
            }
        } else {
            // For normal inline COB, verify no simulated loans are in the list (safety check)
            for (Long loanId : loanIds) {
                Optional<Loan> loanOptional = loanRepository.findById(loanId);
                if (loanOptional.isPresent()) {
                    Loan loan = loanOptional.get();
                    if (Boolean.TRUE.equals(loan.getIsSimulation())) {
                        log.warn("WARNING: Loan [{}] is in simulation mode but this is a NORMAL inline COB. "
                                + "Simulated loans should only be processed via simulation COB. Skipping this loan.", loanId);
                    }
                }
            }
        }

        return loanIdAndLastClosedBusinessDates;
    }

    private List<LoanAccountLock> getLoanAccountLocks(List<Long> loanIds, LocalDate businessDate) {
        List<LoanAccountLock> loanAccountLocks = new ArrayList<>();
        List<Long> alreadyLockedLoanIds = new ArrayList<>();
        loanIds.forEach(loanId -> {
            Optional<LoanAccountLock> loanLockOptional = loanAccountLockRepository.findById(loanId);
            if (loanLockOptional.isPresent()) {
                LoanAccountLock loanAccountLock = loanLockOptional.get();
                if (isLockOverrulable(loanAccountLock)) {
                    loanAccountLocks.add(loanAccountLock);
                } else {
                    alreadyLockedLoanIds.add(loanId);
                }
            } else {
                loanAccountLocks.add(new LoanAccountLock(loanId, LockOwner.LOAN_INLINE_COB_PROCESSING, businessDate));
            }
        });
        if (!alreadyLockedLoanIds.isEmpty()) {
            String message = "There is a hard lock on the loan account without any error, so it can't be overruled.";
            String loanIdsMessage = " Locked loan IDs: " + alreadyLockedLoanIds;
            throw new AccountLockCannotBeOverruledException(message + loanIdsMessage);
        }

        return loanAccountLocks;
    }

    private Map<String, JobParameter<?>> getJobParametersMap(List<Long> loanIds, LocalDate businessDate) {
        // TODO: refactor for a more generic solution
        String parameterJson = gson.toJson(loanIds);
        JobParameterDTO loanIdsParameterDTO = new JobParameterDTO(LoanCOBConstant.LOAN_IDS_PARAMETER_NAME, parameterJson);
        Set<JobParameterDTO> loanIdJobParameter = Collections.singleton(loanIdsParameterDTO);
        Long loanIdsJobParameterId = customJobParameterRepository.save(loanIdJobParameter);
        JobParameterDTO businessDateParameterDTO = new JobParameterDTO(LoanCOBConstant.BUSINESS_DATE_PARAMETER_NAME,
                businessDate.format(DateTimeFormatter.ISO_DATE));
        Set<JobParameterDTO> businessDateJobParameter = Collections.singleton(businessDateParameterDTO);
        Long businessDateJobParameterId = customJobParameterRepository.save(businessDateJobParameter);
        Map<String, JobParameter<?>> jobParameterMap = new HashMap<>();
        jobParameterMap.put(SpringBatchJobConstants.CUSTOM_JOB_PARAMETER_ID_KEY, new JobParameter<>(loanIdsJobParameterId, Long.class));
        jobParameterMap.put(LoanCOBConstant.BUSINESS_DATE_PARAMETER_NAME, new JobParameter<>(businessDateJobParameterId, Long.class));
        return jobParameterMap;
    }

    private void lockLoanAccounts(List<Long> loanIds, LocalDate businessDate) {
        transactionTemplate.setPropagationBehavior(PROPAGATION_REQUIRES_NEW);
        transactionTemplate.execute(new TransactionCallbackWithoutResult() {

            @Override
            protected void doInTransactionWithoutResult(@NonNull TransactionStatus status) {
                List<LoanAccountLock> loanAccountLocks = getLoanAccountLocks(loanIds, businessDate);
                loanAccountLocks.forEach(loanAccountLock -> {
                    try {
                        loanAccountLock.setNewLockOwner(LockOwner.LOAN_INLINE_COB_PROCESSING);
                        loanAccountLockRepository.saveAndFlush(loanAccountLock);
                    } catch (Exception e) {
                        log.error("Error updating lock on loan account. Locked loan ID: {}", loanAccountLock.getLoanId(), e);
                        throw new AccountLockCannotBeOverruledException(
                                "Error updating lock on loan account. Locked loan ID: %s".formatted(loanAccountLock.getLoanId()), e);
                    }
                });
            }
        });
    }

    private boolean isLockOverrulable(LoanAccountLock loanAccountLock) {
        if (isBypassUser()) {
            return true;
        } else {
            return StringUtils.isNotBlank(loanAccountLock.getError());
        }
    }

    private boolean isBypassUser() {
        return context.getAuthenticatedUserIfPresent().isBypassUser();
    }

    private void validateLoanIdsListSize(List<Long> loanIds) {
        int inlineLoanCobRequestItemLimit = fineractProperties.getApi().getBodyItemSizeLimit().getInlineLoanCob();
        if (loanIds.size() > inlineLoanCobRequestItemLimit) {
            String userMessage = "Size of the loan IDs list cannot be over " + inlineLoanCobRequestItemLimit;
            throw new PlatformRequestBodyItemLimitValidationException(userMessage);
        }
    }
}
