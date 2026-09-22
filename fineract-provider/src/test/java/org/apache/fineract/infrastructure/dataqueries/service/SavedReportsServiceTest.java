/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.infrastructure.dataqueries.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.sql.ResultSet;
import java.util.List;
import org.apache.fineract.infrastructure.dataqueries.exception.ReportNotFoundException;
import org.apache.fineract.infrastructure.security.exception.NoAuthorizationException;
import org.apache.fineract.useradministration.domain.AppUser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class SavedReportsServiceTest {

    private JdbcTemplate jdbcTemplate;
    private SavedReportsService service;
    private AppUser user;

    @BeforeEach
    void setUp() {
        jdbcTemplate = mock(JdbcTemplate.class);
        service = new SavedReportsService(jdbcTemplate);
        user = mock(AppUser.class);
        when(user.getId()).thenReturn(7L);
    }

    @Test
    void listReturnsOnlyReportsTheUserCanStillRun() throws Exception {
        when(user.hasNotPermissionForReport("Allowed")).thenReturn(false);
        when(user.hasNotPermissionForReport("Revoked")).thenReturn(true);
        when(jdbcTemplate.query(anyString(), any(RowMapper.class), eq(7L))).thenAnswer(invocation -> {
            RowMapper<?> mapper = invocation.getArgument(1);
            ResultSet first = mock(ResultSet.class);
            when(first.getLong("id")).thenReturn(11L);
            when(first.getString("report_name")).thenReturn("Allowed");
            ResultSet second = mock(ResultSet.class);
            when(second.getLong("id")).thenReturn(12L);
            when(second.getString("report_name")).thenReturn("Revoked");
            return List.of(mapper.mapRow(first, 0), mapper.mapRow(second, 1));
        });

        assertThat(service.list(user)).containsExactly(11L);
    }

    @Test
    void addRejectsReportsWithoutPermission() {
        when(jdbcTemplate.query(anyString(), any(RowMapper.class), eq(11L))).thenReturn(List.of("Restricted"));
        when(user.hasNotPermissionForReport("Restricted")).thenReturn(true);

        assertThatThrownBy(() -> service.add(user, 11L)).isInstanceOf(NoAuthorizationException.class);
    }

    @Test
    void addRejectsReportsNotMarkedForUse() {
        when(jdbcTemplate.query(anyString(), any(RowMapper.class), eq(11L))).thenReturn(List.of());

        assertThatThrownBy(() -> service.add(user, 11L)).isInstanceOf(ReportNotFoundException.class);
    }

    @Test
    void addSavesOnlyForTheAuthenticatedUser() {
        when(jdbcTemplate.query(anyString(), any(RowMapper.class), eq(11L))).thenReturn(List.of("Allowed"));

        service.add(user, 11L);

        verify(jdbcTemplate).update("INSERT INTO m_appuser_saved_report (appuser_id, report_id) VALUES (?, ?) ON CONFLICT DO NOTHING", 7L,
                11L);
    }

    @Test
    void removeOnlyTargetsTheAuthenticatedUsersRow() {
        service.remove(user, 11L);

        verify(jdbcTemplate).update("DELETE FROM m_appuser_saved_report WHERE appuser_id = ? AND report_id = ?", 7L, 11L);
    }
}
