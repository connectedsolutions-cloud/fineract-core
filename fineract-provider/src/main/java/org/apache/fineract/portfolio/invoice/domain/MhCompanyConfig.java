package org.apache.fineract.portfolio.invoice.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.io.Serializable;
import lombok.Getter;
import lombok.Setter;

/**
 * Tenant-level MH / firma defaults (single logical row with id = 1). Office-level columns override per
 * {@link org.apache.fineract.organisation.office.domain.Office}.
 */
@Entity
@Table(name = "m_mh_company_config")
@Getter
@Setter
public class MhCompanyConfig implements Serializable {

    public static final long SINGLETON_ID = 1L;

    @Id
    @Column(name = "id", nullable = false)
    private Long id;

    @Column(name = "nit", length = 20)
    private String nit;

    @Column(name = "password_pri", length = 500)
    private String passwordPri;

    @Column(name = "firma_secret", length = 255)
    private String firmaSecret;

    @Column(name = "signing_api_key", length = 255)
    private String signingApiKey;

    protected MhCompanyConfig() {}

    public static MhCompanyConfig emptySingleton() {
        MhCompanyConfig c = new MhCompanyConfig();
        c.id = SINGLETON_ID;
        return c;
    }
}
