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
package org.apache.fineract.portfolio.interestpauses.service;

import static org.apache.fineract.portfolio.loanaccount.domain.LoanStatus.ACTIVE;
import static org.apache.fineract.portfolio.loanaccount.domain.LoanTermVariationType.INTEREST_PAUSE;
import static org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleType.CUMULATIVE;
import static org.apache.fineract.portfolio.loanaccount.loanschedule.domain.LoanScheduleType.PROGRESSIVE;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import lombok.AllArgsConstructor;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResult;
import org.apache.fineract.infrastructure.core.data.CommandProcessingResultBuilder;
import org.apache.fineract.infrastructure.core.domain.ExternalId;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.apache.fineract.infrastructure.core.exception.PlatformApiDataValidationException;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.infrastructure.event.business.domain.loan.LoanBalanceChangedBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.loan.LoanScheduleVariationsAddedBusinessEvent;
import org.apache.fineract.infrastructure.event.business.domain.loan.LoanScheduleVariationsDeletedBusinessEvent;
import org.apache.fineract.infrastructure.event.business.service.BusinessEventNotifierService;
import org.apache.fineract.portfolio.common.service.Validator;
import org.apache.fineract.portfolio.loanaccount.domain.Loan;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepaymentScheduleInstallment;
import org.apache.fineract.portfolio.loanaccount.domain.LoanRepositoryWrapper;
import org.apache.fineract.portfolio.loanaccount.domain.LoanTermVariations;
import org.apache.fineract.portfolio.loanaccount.domain.transactionprocessor.impl.CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor;
import org.apache.fineract.portfolio.loanaccount.rescheduleloan.domain.LoanTermVariationsRepository;
import org.apache.fineract.portfolio.loanaccount.service.LoanAssembler;
import org.apache.fineract.portfolio.loanaccount.service.LoanScheduleService;
import org.apache.fineract.portfolio.loanproduct.domain.InterestCalculationPeriodMethod;
import org.springframework.transaction.annotation.Transactional;

@AllArgsConstructor
@Transactional
public class InterestPauseWritePlatformServiceImpl implements InterestPauseWritePlatformService {

    private final LoanTermVariationsRepository loanTermVariationsRepository;
    private final LoanRepositoryWrapper loanRepositoryWrapper;
    private final LoanAssembler loanAssembler;
    private final BusinessEventNotifierService businessEventNotifierService;
    private final LoanScheduleService loanScheduleService;

    @Override
    public CommandProcessingResult createInterestPause(final ExternalId loanExternalId, final String startDateString,
            final String endDateString, final String dateFormat, final String locale) {
        final LocalDate startDate = parseDate(startDateString, dateFormat, locale);
        final LocalDate endDate = parseDate(endDateString, dateFormat, locale);
        final Loan loan = loanAssembler.assembleFrom(loanExternalId, false);

        return processInterestPause(loan, startDate, endDate, dateFormat, locale);
    }

    @Override
    public CommandProcessingResult createInterestPause(final Long loanId, final String startDateString, final String endDateString,
            final String dateFormat, final String locale) {
        final LocalDate startDate = parseDate(startDateString, dateFormat, locale);
        final LocalDate endDate = parseDate(endDateString, dateFormat, locale);
        final Loan loan = loanAssembler.assembleFrom(loanId, false);

        return processInterestPause(loan, startDate, endDate, dateFormat, locale);
    }

    @Override
    public CommandProcessingResult deleteInterestPause(ExternalId loanExternalId, Long variationId) {
        return processDeleteInterestPause(loanRepositoryWrapper.findOneWithNotFoundDetection(loanExternalId), variationId);
    }

    @Override
    public CommandProcessingResult deleteInterestPause(Long loanId, Long variationId) {
        return processDeleteInterestPause(loanRepositoryWrapper.findOneWithNotFoundDetection(loanId), variationId);
    }

    @Override
    public CommandProcessingResult updateInterestPause(ExternalId loanExternalId, Long variationId, String startDateString,
            String endDateString, String dateFormat, String locale) {
        return processUpdateInterestPause(loanRepositoryWrapper.findOneWithNotFoundDetection(loanExternalId), variationId, startDateString,
                endDateString, dateFormat, locale);
    }

    @Override
    public CommandProcessingResult updateInterestPause(Long loanId, Long variationId, String startDateString, String endDateString,
            String dateFormat, String locale) {
        return processUpdateInterestPause(loanRepositoryWrapper.findOneWithNotFoundDetection(loanId), variationId, startDateString,
                endDateString, dateFormat, locale);
    }

    private CommandProcessingResult processDeleteInterestPause(Loan loan, Long variationId) {
        validateActiveLoan(loan);

        LoanTermVariations variation = loanTermVariationsRepository
                .findByIdAndLoanIdAndTermType(variationId, loan.getId(), INTEREST_PAUSE.getValue())
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.variation.not.found",
                        "Variation not found for the given loan ID"));

        if (isCredesalCumulativeLoan(loan) && !variation.getTermApplicableFrom().isAfter(DateUtils.getBusinessLocalDate())) {
            throw new GeneralPlatformDomainRuleException("interest.pause.started.cannot.be.deleted",
                    "A Credesal interest pause that has already started cannot be deleted.");
        }

        final List<HistoricalInstallment> historicalSchedule = historicalSchedule(loan, variation.getTermApplicableFrom());
        loanTermVariationsRepository.delete(variation);
        loan.getLoanTermVariations().remove(variation);

        if (scheduledInterestIsAffected(loan, variation.getTermApplicableFrom())) {
            regenerateAndAssertHistoricalSchedule(loan, variation.getTermApplicableFrom(), historicalSchedule);
        }

        businessEventNotifierService.notifyPostBusinessEvent(new LoanScheduleVariationsDeletedBusinessEvent(loan));
        businessEventNotifierService.notifyPostBusinessEvent(new LoanBalanceChangedBusinessEvent(loan));

        return new CommandProcessingResultBuilder().withEntityId(variationId).build();
    }

    private CommandProcessingResult processUpdateInterestPause(Loan loan, Long variationId, String startDateString, String endDateString,
            String dateFormat, String locale) {
        LocalDate startDate = parseDate(startDateString, dateFormat, locale);
        LocalDate endDate = parseDate(endDateString, dateFormat, locale);

        validateActiveLoan(loan);

        LoanTermVariations variation = loanTermVariationsRepository
                .findByIdAndLoanIdAndTermType(variationId, loan.getId(), INTEREST_PAUSE.getValue())
                .orElseThrow(() -> new GeneralPlatformDomainRuleException("error.msg.variation.not.found",
                        "Variation not found for the given loan ID"));

        if (isCredesalCumulativeLoan(loan) && !variation.getTermApplicableFrom().isAfter(DateUtils.getBusinessLocalDate())) {
            throw new GeneralPlatformDomainRuleException("interest.pause.started.cannot.be.updated",
                    "A Credesal interest pause that has already started cannot be updated.");
        }

        validateInterestPauseDates(loan, startDate, endDate, dateFormat, locale, variation.getId());

        final LocalDate previousStartDate = variation.getTermApplicableFrom();
        final LocalDate protectedStartDate = previousStartDate.isBefore(startDate) ? previousStartDate : startDate;
        final List<HistoricalInstallment> historicalSchedule = historicalSchedule(loan, protectedStartDate);

        variation.setTermApplicableFrom(startDate);
        variation.setDateValue(endDate);

        LoanTermVariations updatedVariation = loanTermVariationsRepository.save(variation);

        if (scheduledInterestIsAffected(loan, previousStartDate) || scheduledInterestIsAffected(loan, startDate)) {
            regenerateAndAssertHistoricalSchedule(loan, protectedStartDate, historicalSchedule);
        }

        businessEventNotifierService.notifyPostBusinessEvent(new LoanScheduleVariationsAddedBusinessEvent(loan));
        businessEventNotifierService.notifyPostBusinessEvent(new LoanBalanceChangedBusinessEvent(loan));

        return new CommandProcessingResultBuilder().withEntityId(updatedVariation.getId())
                .with(Map.of("startDate", startDate.toString(), "endDate", endDate.toString())).build();
    }

    private CommandProcessingResult processInterestPause(final Loan loan, final LocalDate startDate, final LocalDate endDate,
            String dateFormat, String locale) {
        validateActiveLoan(loan);
        validateInterestPauseDates(loan, startDate, endDate, dateFormat, locale, null);

        final List<HistoricalInstallment> historicalSchedule = historicalSchedule(loan, startDate);

        final LoanTermVariations variation = new LoanTermVariations(INTEREST_PAUSE.getValue(), startDate, BigDecimal.ZERO, endDate, false,
                loan);

        final LoanTermVariations savedVariation = loanTermVariationsRepository.saveAndFlush(variation);
        loan.getLoanTermVariations().add(savedVariation);

        if (scheduledInterestIsAffected(loan, startDate)) {
            regenerateAndAssertHistoricalSchedule(loan, startDate, historicalSchedule);
        }

        businessEventNotifierService.notifyPostBusinessEvent(new LoanScheduleVariationsAddedBusinessEvent(loan));
        businessEventNotifierService.notifyPostBusinessEvent(new LoanBalanceChangedBusinessEvent(loan));

        return new CommandProcessingResultBuilder().withEntityId(savedVariation.getId()).build();
    }

    private void validateInterestPauseDates(Loan loan, LocalDate startDate, LocalDate endDate, String dateFormat, String locale,
            Long currentVariationId) {

        Validator.validateOrThrow("InterestPause", baseDataValidator -> {
            baseDataValidator.reset().parameter("startDate").value(startDate).notBlank();
            baseDataValidator.reset().parameter("endDate").value(endDate).notBlank();
            baseDataValidator.reset().parameter("dateFormat").value(dateFormat).notBlank();
            baseDataValidator.reset().parameter("locale").value(locale).notBlank();
        });

        if (startDate.isBefore(loan.getSubmittedOnDate())) {
            throw new GeneralPlatformDomainRuleException("interest.pause.start.date.before.loan.start.date",
                    String.format("Interest pause start date (%s) cannot be earlier than loan start date (%s).", startDate,
                            loan.getSubmittedOnDate()),
                    startDate, loan.getSubmittedOnDate());
        }

        final boolean credesalCumulative = isCredesalCumulativeLoan(loan);
        if (!credesalCumulative && endDate.isAfter(loan.getMaturityDate())) {
            throw new GeneralPlatformDomainRuleException("interest.pause.end.date.after.loan.maturity.date", String
                    .format("Interest pause end date (%s) cannot be later than loan maturity date (%s).", endDate, loan.getMaturityDate()),
                    endDate, loan.getMaturityDate());
        }

        if (endDate.isBefore(startDate)) {
            throw new GeneralPlatformDomainRuleException("interest.pause.end.date.before.start.date", String
                    .format("Interest pause end date (%s) must not be before the interest pause start date (%s).", endDate, startDate),
                    endDate, startDate);
        }

        if (!PROGRESSIVE.equals(loan.getLoanRepaymentScheduleDetail().getLoanScheduleType()) && !credesalCumulative) {
            throw new GeneralPlatformDomainRuleException("loan.must.be.progressive", "Interest pause is supported for progressive loans or"
                    + " Credesal cumulative loans with daily declining-balance interest.");
        }

        if (!loan.isInterestBearing()) {
            throw new GeneralPlatformDomainRuleException("loan.must.be.interest.bearing",
                    "Interest pause is only supported for interest bearing loans.");
        }

        if (!loan.getLoanRepaymentScheduleDetail().isInterestRecalculationEnabled() && !credesalCumulative) {
            throw new GeneralPlatformDomainRuleException("loan.must.have.recalculate.interest.enabled",
                    "Interest pause is only supported for loans with recalculate interest enabled.");
        }

        // Historical accounting and source-exact repayment allocations must not be repriced by a backdated pause.
        if (credesalCumulative && !startDate.isAfter(DateUtils.getBusinessLocalDate())) {
            throw new GeneralPlatformDomainRuleException("interest.pause.start.date.must.follow.business.date",
                    "Credesal interest pauses must start after the current business date.");
        }

        if (credesalCumulative && loan.getRepaymentScheduleInstallments().stream().filter(installment -> !installment.isAdditional())
                .anyMatch(installment -> installment.getFromDate() != null && installment.getFromDate().isBefore(endDate)
                        && !installment.getDueDate().isBefore(startDate) && (positive(installment.getInterestPaid())
                                || positive(installment.getInterestWaived()) || positive(installment.getInterestWrittenOff())))) {
            throw new GeneralPlatformDomainRuleException("interest.pause.future.interest.already.settled",
                    "A Credesal interest pause cannot change an installment whose future interest has already been settled.");
        }

        List<LoanTermVariations> existingVariations = loan.getLoanTermVariations();
        for (LoanTermVariations existingVariation : existingVariations) {
            if (currentVariationId == null || !existingVariation.getId().equals(currentVariationId)) {
                if (Objects.equals(existingVariation.getTermType().getValue(), INTEREST_PAUSE.getValue())) {
                    if (!(endDate.isBefore(existingVariation.getTermApplicableFrom())
                            || startDate.isAfter(existingVariation.getDateValue()))) {
                        throw new GeneralPlatformDomainRuleException("interest.pause.overlapping",
                                "Overlapping interest pauses are not allowed.");
                    }
                }
            }
        }
    }

    private boolean isCredesalCumulativeLoan(final Loan loan) {
        return CUMULATIVE.equals(loan.getLoanRepaymentScheduleDetail().getLoanScheduleType())
                && CredesalAccruedInterestLoanRepaymentScheduleTransactionProcessor.STRATEGY_CODE
                        .equals(loan.transactionProcessingStrategy())
                && loan.getLoanRepaymentScheduleDetail().getInterestMethod() != null
                && loan.getLoanRepaymentScheduleDetail().getInterestMethod().isDecliningBalance()
                && InterestCalculationPeriodMethod.DAILY.equals(loan.getLoanRepaymentScheduleDetail().getInterestCalculationPeriodMethod());
    }

    private record HistoricalInstallment(Integer number, LocalDate dueDate, BigDecimal principal, BigDecimal interest, BigDecimal fee,
            BigDecimal penalty) {
    }

    private List<HistoricalInstallment> historicalSchedule(final Loan loan, final LocalDate pauseStart) {
        if (!isCredesalCumulativeLoan(loan)) {
            return List.of();
        }
        return loan.getRepaymentScheduleInstallments().stream().filter(installment -> installment.getDueDate().isBefore(pauseStart))
                .map(installment -> new HistoricalInstallment(installment.getInstallmentNumber(), installment.getDueDate(),
                        normalized(installment.getPrincipal()), normalized(installment.getInterestCharged()),
                        normalized(installment.getFeeChargesCharged()), normalized(installment.getPenaltyCharges())))
                .toList();
    }

    private BigDecimal normalized(final BigDecimal amount) {
        return (amount == null ? BigDecimal.ZERO : amount).stripTrailingZeros();
    }

    private boolean positive(final BigDecimal amount) {
        return amount != null && amount.signum() > 0;
    }

    private void assertHistoricalScheduleUnchanged(final Loan loan, final LocalDate pauseStart,
            final List<HistoricalInstallment> historicalSchedule) {
        if (isCredesalCumulativeLoan(loan) && !historicalSchedule.equals(historicalSchedule(loan, pauseStart))) {
            throw new GeneralPlatformDomainRuleException("interest.pause.changes.historical.schedule",
                    "The Credesal interest pause would change installments before its start date.");
        }
    }

    private boolean scheduledInterestIsAffected(final Loan loan, final LocalDate pauseStart) {
        if (isCredesalCumulativeLoan(loan) && loan.getRepaymentScheduleInstallments().stream()
                .anyMatch(installment -> installment.isMigrationMetricBaseline() && installment.getMigrationInterestForecast() != null)) {
            // An aligned loan earns actual-principal interest through its baseline calculator,
            // which reads pause periods directly. Regeneration would destroy that accepted state.
            return false;
        }
        return !isCredesalCumulativeLoan(loan) || loan.getRepaymentScheduleInstallments().stream()
                .filter(installment -> !installment.isAdditional()).map(LoanRepaymentScheduleInstallment::getDueDate)
                .max(LocalDate::compareTo).map(lastDueDate -> !lastDueDate.isBefore(pauseStart)).orElse(false);
    }

    private void regenerateAndAssertHistoricalSchedule(final Loan loan, final LocalDate pauseStart,
            final List<HistoricalInstallment> historicalSchedule) {
        loanScheduleService.regenerateScheduleWithReprocessingTransactions(loan);
        assertHistoricalScheduleUnchanged(loan, pauseStart, historicalSchedule);
    }

    private void validateActiveLoan(Loan loan) {
        if (!Objects.equals(loan.getLoanStatus(), ACTIVE)) {
            throw new GeneralPlatformDomainRuleException("loan.must.be.active",
                    "Operations on interest pauses are restricted to active loans.");
        }
    }

    private LocalDate parseDate(String date, String dateFormat, String locale) {
        try {
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern(dateFormat, Locale.forLanguageTag(locale));
            return LocalDate.parse(date, formatter);
        } catch (DateTimeParseException e) {
            throw new PlatformApiDataValidationException("validation.msg.invalid.date.format",
                    String.format("Invalid date format. Provided: %s, Expected format: %s, Locale: %s", date, dateFormat, locale),
                    e.getMessage(), e);
        }
    }
}
