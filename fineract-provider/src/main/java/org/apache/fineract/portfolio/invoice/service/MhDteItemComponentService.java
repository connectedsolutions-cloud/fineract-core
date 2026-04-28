package org.apache.fineract.portfolio.invoice.service;

import java.util.List;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentPreviewData;
import org.apache.fineract.portfolio.invoice.data.MhDteItemComponentRequest;

public interface MhDteItemComponentService {

    List<MhDteItemComponentData> retrieveAll();

    MhDteItemComponentData retrieveOne(Long id);

    MhDteItemComponentData create(MhDteItemComponentRequest request);

    MhDteItemComponentData update(Long id, MhDteItemComponentRequest request);

    void delete(Long id);

    MhDteItemComponentPreviewData preview(Long loanTransactionId, String clientType, boolean includeJournalEntries);
}
