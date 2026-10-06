package org.apache.fineract.portfolio.treasury.service;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.apache.fineract.accounting.journalentry.service.JournalNumberAllocationService;
import org.apache.fineract.infrastructure.core.exception.GeneralPlatformDomainRuleException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JournalReferenceNumberService implements JournalNumberAllocationService {

    private static final DateTimeFormatter PERIOD = DateTimeFormatter.ofPattern("yyyyMM");

    @PersistenceContext
    private EntityManager entityManager;

    /**
     * Advance each monthly counter to the highest assigned Arissto journal number for the frozen accounting boundary,
     * including numbers assigned to unposted headers. Repeated calls never lower an already used counter. The number
     * prefix, rather than entry_date, owns the sequence because Arissto has a reviewed back-period exception.
     */
    @Transactional
    public Map<String, Object> seedImported(LocalDate cutoffDate, Map<String, Integer> sourceMaxima) {
        Number invalid = (Number) entityManager.createNativeQuery("""
                SELECT COUNT(*) FROM credesal_arissto_gl_journal
                WHERE result = 'IMPORTED' AND cutoff_date = ?1
                  AND (target_ref_num IS NULL OR target_ref_num !~ '^[0-9]{10}$'
                       OR target_ref_num <> source_journal_number)
                """).setParameter(1, cutoffDate).getSingleResult();
        if (invalid.longValue() != 0) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.invalid",
                    "Imported Arissto journal numbers are missing, malformed, or changed");
        }
        Number collisions = (Number) entityManager.createNativeQuery("""
                SELECT COUNT(*) FROM credesal_arissto_gl_journal p
                JOIN acc_gl_journal_entry j ON j.ref_num = p.target_ref_num
                WHERE p.result = 'IMPORTED' AND p.cutoff_date = ?1
                  AND j.transaction_id <> p.target_transaction_id
                """).setParameter(1, cutoffDate).getSingleResult();
        if (collisions.longValue() != 0) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.collision",
                    "An imported Arissto journal number is already owned by another Fineract transaction");
        }
        @SuppressWarnings("unchecked")
        List<Object[]> imported = entityManager.createNativeQuery("""
                SELECT SUBSTRING(target_ref_num FROM 1 FOR 6) AS period_key,
                       MAX(CAST(SUBSTRING(target_ref_num FROM 7 FOR 4) AS INTEGER)) AS last_value
                FROM credesal_arissto_gl_journal
                WHERE result = 'IMPORTED' AND cutoff_date = ?1
                GROUP BY SUBSTRING(target_ref_num FROM 1 FOR 6)
                ORDER BY period_key
                """).setParameter(1, cutoffDate).getResultList();
        if (imported.isEmpty()) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.empty",
                    "No imported Arissto journals exist for this accounting cutoff");
        }
        if (sourceMaxima == null || sourceMaxima.isEmpty()) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.source.empty",
                    "The frozen Arissto journal-number highwater is required");
        }
        for (Map.Entry<String, Integer> sourcePeriod : sourceMaxima.entrySet()) {
            String period = sourcePeriod.getKey();
            Integer maximum = sourcePeriod.getValue();
            if (period == null || !period.matches("[0-9]{6}") || Integer.parseInt(period.substring(4)) < 1
                    || Integer.parseInt(period.substring(4)) > 12 || maximum == null || maximum < 1 || maximum > 9999) {
                throw new GeneralPlatformDomainRuleException("error.msg.journal.number.source.invalid",
                        "The frozen Arissto journal-number highwater is invalid");
            }
        }
        Map<String, Integer> importedMaxima = new LinkedHashMap<>();
        for (Object[] row : imported) {
            importedMaxima.put((String) row[0], ((Number) row[1]).intValue());
        }
        for (Map.Entry<String, Integer> importedPeriod : importedMaxima.entrySet()) {
            if (sourceMaxima.getOrDefault(importedPeriod.getKey(), 0) < importedPeriod.getValue()) {
                throw new GeneralPlatformDomainRuleException("error.msg.journal.number.source.below.import",
                        "The frozen Arissto highwater is below an imported journal number");
            }
        }
        int raised = 0;
        Map<String, Integer> maxima = new LinkedHashMap<>();
        for (Map.Entry<String, Integer> sourcePeriod : new TreeMap<>(sourceMaxima).entrySet()) {
            String period = sourcePeriod.getKey();
            Integer sourceMaximum = sourcePeriod.getValue();
            entityManager.createNativeQuery(
                    "INSERT INTO m_gl_journal_number_sequence (period_key, last_value) VALUES (?1, 0) ON CONFLICT (period_key) DO NOTHING")
                    .setParameter(1, period).executeUpdate();
            Number current = (Number) entityManager
                    .createNativeQuery("SELECT last_value FROM m_gl_journal_number_sequence WHERE period_key = ?1 FOR UPDATE")
                    .setParameter(1, period).getSingleResult();
            Number targetMaximum = (Number) entityManager.createNativeQuery("""
                    SELECT COALESCE(MAX(CAST(SUBSTRING(ref_num FROM 7 FOR 4) AS INTEGER)), 0)
                    FROM acc_gl_journal_entry
                    WHERE ref_num ~ '^[0-9]{10}$' AND SUBSTRING(ref_num FROM 1 FOR 6) = ?1
                    """).setParameter(1, period).getSingleResult();
            int next = Math.max(Math.max(current.intValue(), sourceMaximum), targetMaximum.intValue());
            if (next > current.intValue()) {
                entityManager.createNativeQuery("UPDATE m_gl_journal_number_sequence SET last_value = ?1 WHERE period_key = ?2")
                        .setParameter(1, next).setParameter(2, period).executeUpdate();
                raised++;
            }
            maxima.put(period, next);
        }
        return Map.of("cutoffDate", cutoffDate.toString(), "periods", maxima, "raised", raised);
    }

    /** All native GL writers, including treasury, reserve by one stable journal-group key. */
    @Override
    @Transactional
    public String assign(String groupKey, LocalDate transactionDate) {
        if (groupKey == null || groupKey.isBlank() || groupKey.length() > 128 || transactionDate == null) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.group.invalid", "A journal group and date are required");
        }
        String period = transactionDate.format(PERIOD);
        int current = lockCounter(period);
        Object[] existing = assignment(groupKey);
        if (existing != null) {
            if (!period.equals(existing[0]) || !"GENERATED".equals(existing[2])) {
                throw new GeneralPlatformDomainRuleException("error.msg.journal.number.group.period",
                        "A journal group cannot change accounting month");
            }
            return (String) existing[1];
        }
        Number targetMaximum = (Number) entityManager.createNativeQuery("""
                SELECT COALESCE(MAX(CAST(SUBSTRING(ref_num FROM 7 FOR 4) AS INTEGER)), 0)
                FROM acc_gl_journal_entry
                WHERE ref_num ~ '^[0-9]{10}$' AND SUBSTRING(ref_num FROM 1 FOR 6) = ?1
                """).setParameter(1, period).getSingleResult();
        int next = Math.max(current, targetMaximum.intValue()) + 1;
        if (next > 9999) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.exhausted",
                    "The monthly journal number sequence is full for " + period);
        }
        String number = period + String.format("%04d", next);
        entityManager.createNativeQuery("UPDATE m_gl_journal_number_sequence SET last_value = ?1 WHERE period_key = ?2")
                .setParameter(1, next).setParameter(2, period).executeUpdate();
        entityManager.createNativeQuery("""
                INSERT INTO m_gl_journal_number_assignment (group_key, period_key, ref_num, assignment_type)
                VALUES (?1, ?2, ?3, 'GENERATED')
                """).setParameter(1, groupKey).setParameter(2, period).setParameter(3, number).executeUpdate();
        return number;
    }

    /** Exact source numbers are retained, with database uniqueness across imported and native groups. */
    @Override
    @Transactional
    public String reserveImported(String groupKey, String transactionId, String number) {
        if (groupKey == null || groupKey.isBlank() || groupKey.length() > 128 || transactionId == null
                || transactionId.isBlank() || number == null
                || !number.matches("[0-9]{10}") || Integer.parseInt(number.substring(4, 6)) < 1
                || Integer.parseInt(number.substring(4, 6)) > 12 || Integer.parseInt(number.substring(6)) < 1) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.invalid",
                    "An imported journal must have its exact ten-digit source number");
        }
        String period = number.substring(0, 6);
        int current = lockCounter(period);
        Object[] existing = assignment(groupKey);
        if (existing != null) {
            if (!period.equals(existing[0]) || !number.equals(existing[1]) || !"IMPORTED".equals(existing[2])) {
                throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.changed",
                        "An imported journal group cannot change its source number");
            }
            return number;
        }
        Number collision = (Number) entityManager.createNativeQuery("""
                SELECT COUNT(*) FROM acc_gl_journal_entry WHERE ref_num = ?1 AND transaction_id <> ?2
                """).setParameter(1, number).setParameter(2, transactionId).getSingleResult();
        if (collision.longValue() != 0) {
            throw new GeneralPlatformDomainRuleException("error.msg.journal.number.import.collision",
                    "The imported journal number is owned by another transaction");
        }
        // Unique ref_num on the assignment table also rejects a concurrent or already reserved owner.
        entityManager.createNativeQuery("""
                INSERT INTO m_gl_journal_number_assignment (group_key, period_key, ref_num, assignment_type)
                VALUES (?1, ?2, ?3, 'IMPORTED')
                """).setParameter(1, groupKey).setParameter(2, period).setParameter(3, number).executeUpdate();
        int sourceNumber = Integer.parseInt(number.substring(6));
        if (sourceNumber > current) {
            entityManager.createNativeQuery("UPDATE m_gl_journal_number_sequence SET last_value = ?1 WHERE period_key = ?2")
                    .setParameter(1, sourceNumber).setParameter(2, period).executeUpdate();
        }
        return number;
    }

    private int lockCounter(String period) {
        entityManager.createNativeQuery(
                "INSERT INTO m_gl_journal_number_sequence (period_key, last_value) VALUES (?1, 0) ON CONFLICT (period_key) DO NOTHING")
                .setParameter(1, period).executeUpdate();
        Number current = (Number) entityManager
                .createNativeQuery("SELECT last_value FROM m_gl_journal_number_sequence WHERE period_key = ?1 FOR UPDATE")
                .setParameter(1, period).getSingleResult();
        return current.intValue();
    }

    private Object[] assignment(String groupKey) {
        @SuppressWarnings("unchecked")
        List<Object[]> rows = entityManager.createNativeQuery("""
                SELECT period_key, ref_num, assignment_type FROM m_gl_journal_number_assignment WHERE group_key = ?1
                """).setParameter(1, groupKey).getResultList();
        return rows.isEmpty() ? null : rows.get(0);
    }

    /** A journal group key is mandatory; callers must use assign(groupKey, transactionDate). */
    @Deprecated
    @Transactional
    public String assign(LocalDate transactionDate) {
        throw new GeneralPlatformDomainRuleException("error.msg.journal.number.group.required",
                "A stable journal group key is required for monthly numbering");
    }

}
