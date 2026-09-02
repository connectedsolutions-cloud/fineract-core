package org.apache.fineract.portfolio.invoice.mh;

import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.apache.fineract.infrastructure.core.exception.PlatformDataIntegrityException;
import org.apache.fineract.organisation.office.domain.Office;
import org.apache.fineract.organisation.office.domain.OfficeRepository;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfig;
import org.apache.fineract.portfolio.invoice.domain.MhCompanyConfigRepository;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class MhFirmaCredentialResolver {

    private final MhCompanyConfigRepository mhCompanyConfigRepository;
    private final OfficeRepository officeRepository;

    public MhFirmaCredentials resolve(Long officeId) {
        MhCompanyConfig company = mhCompanyConfigRepository.findById(MhCompanyConfig.SINGLETON_ID)
                .orElseGet(MhCompanyConfig::emptySingleton);
        Office office = officeId != null ? officeRepository.findById(officeId).orElse(null) : null;

        String rawNit = firstNonBlank(office != null ? office.getMhNit() : null, company.getNit());
        String nit14 = NitNormalizer.toFourteenDigits(rawNit);
        if (nit14 == null || nit14.length() != 14) {
            throw new PlatformDataIntegrityException("error.msg.mh.nit.missing", "MH NIT is not configured (company or office)", officeId);
        }
        String passwordPri = firstNonBlank(office != null ? office.getMhPasswordPri() : null, company.getPasswordPri());
        if (StringUtils.isBlank(passwordPri)) {
            throw new PlatformDataIntegrityException("error.msg.mh.password.missing", "MH private key password is not configured",
                    officeId);
        }
        String signingApiKey = firstNonBlank(office != null ? office.getMhSigningApiKey() : null, company.getSigningApiKey());
        String firmaSecret = firstNonBlank(office != null ? office.getMhFirmaSecret() : null, company.getFirmaSecret());
        return new MhFirmaCredentials(nit14, passwordPri, signingApiKey, firmaSecret);
    }

    private static String firstNonBlank(String a, String b) {
        if (StringUtils.isNotBlank(a)) {
            return a;
        }
        return StringUtils.isNotBlank(b) ? b : null;
    }
}
