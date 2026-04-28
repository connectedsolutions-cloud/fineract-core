package org.apache.fineract.portfolio.invoice.domain;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

public interface MhDteItemComponentRepository extends JpaRepository<MhDteItemComponent, Long> {

    List<MhDteItemComponent> findAllByOrderByTargetUqAscClientTypeKeyAsc();
}
