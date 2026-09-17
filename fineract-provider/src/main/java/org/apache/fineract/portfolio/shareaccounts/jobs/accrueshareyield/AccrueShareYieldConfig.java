/** Licensed to the Apache Software Foundation (ASF) under one or more contributor license agreements. */
package org.apache.fineract.portfolio.shareaccounts.jobs.accrueshareyield;

import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.jobs.service.JobName;
import org.apache.fineract.portfolio.shareaccounts.service.ShareYieldService;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.Step;
import org.springframework.batch.core.job.builder.JobBuilder;
import org.springframework.batch.core.launch.support.RunIdIncrementer;
import org.springframework.batch.core.repository.JobRepository;
import org.springframework.batch.core.step.builder.StepBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.PlatformTransactionManager;

@Configuration
@RequiredArgsConstructor
public class AccrueShareYieldConfig {

    private final JobRepository jobRepository;
    private final PlatformTransactionManager transactionManager;
    private final ShareYieldService shareYieldService;

    @Bean
    protected Step accrueShareYieldStep() {
        return new StepBuilder(JobName.ACCRUE_SHARE_YIELD.name(), jobRepository)
                .tasklet(new AccrueShareYieldTasklet(shareYieldService), transactionManager).build();
    }

    @Bean
    public Job accrueShareYieldJob() {
        return new JobBuilder(JobName.ACCRUE_SHARE_YIELD.name(), jobRepository).start(accrueShareYieldStep())
                .incrementer(new RunIdIncrementer()).build();
    }
}
