/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements. See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to you under the Apache License, Version 2.0.
 */
package org.apache.fineract.infrastructure.dataqueries.service;

import java.util.List;
import lombok.RequiredArgsConstructor;
import org.apache.fineract.infrastructure.dataqueries.exception.ReportNotFoundException;
import org.apache.fineract.infrastructure.security.exception.NoAuthorizationException;
import org.apache.fineract.useradministration.domain.AppUser;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class SavedReportsService {

    private final JdbcTemplate jdbcTemplate;

    public List<Long> list(final AppUser user) {
        return jdbcTemplate.query("""
                SELECT report.id, report.report_name
                  FROM m_appuser_saved_report saved
                  JOIN stretchy_report report ON report.id = saved.report_id
                 WHERE saved.appuser_id = ? AND report.use_report = true
                 ORDER BY report.report_name
                """, (rs, rowNum) -> new SavedReport(rs.getLong("id"), rs.getString("report_name")), user.getId()).stream()
                .filter(report -> !user.hasNotPermissionForReport(report.name())).map(SavedReport::id).toList();
    }

    @Transactional
    public void add(final AppUser user, final Long reportId) {
        final List<String> names = jdbcTemplate.query("SELECT report_name FROM stretchy_report WHERE id = ? AND use_report = true",
                (rs, rowNum) -> rs.getString("report_name"), reportId);
        if (names.isEmpty()) {
            throw new ReportNotFoundException(reportId);
        }
        if (user.hasNotPermissionForReport(names.get(0))) {
            throw new NoAuthorizationException("Not authorised to save report: " + names.get(0));
        }
        jdbcTemplate.update("INSERT INTO m_appuser_saved_report (appuser_id, report_id) VALUES (?, ?) ON CONFLICT DO NOTHING", user.getId(),
                reportId);
    }

    @Transactional
    public void remove(final AppUser user, final Long reportId) {
        jdbcTemplate.update("DELETE FROM m_appuser_saved_report WHERE appuser_id = ? AND report_id = ?", user.getId(), reportId);
    }

    private record SavedReport(Long id, String name) {
    }
}
