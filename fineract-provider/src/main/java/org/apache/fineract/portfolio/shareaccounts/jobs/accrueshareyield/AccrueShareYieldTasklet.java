/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.jobs.accrueshareyield;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.core.service.DateUtils;
import org.apache.fineract.portfolio.shareaccounts.service.ShareYieldService;
import org.springframework.batch.core.StepContribution;
import org.springframework.batch.core.scope.context.ChunkContext;
import org.springframework.batch.core.step.tasklet.Tasklet;
import org.springframework.batch.repeat.RepeatStatus;

@RequiredArgsConstructor
public class AccrueShareYieldTasklet implements Tasklet {

    private final ShareYieldService shareYieldService;

    @Override
    public RepeatStatus execute(StepContribution contribution, ChunkContext chunkContext) {
        shareYieldService.accrueThrough(DateUtils.getBusinessLocalDate().minusDays(1));
        return RepeatStatus.FINISHED;
    }
}
