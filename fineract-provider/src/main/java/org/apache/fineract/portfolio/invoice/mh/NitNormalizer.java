package org.apache.fineract.portfolio.invoice.mh;

import org.apache.commons.lang3.StringUtils;

public final class NitNormalizer {

    private NitNormalizer() {}

    /**
     * Firma API requires exactly 14 digits for NIT (digits only, left-padded).
     */
    public static String toFourteenDigits(String nit) {
        if (StringUtils.isBlank(nit)) {
            return null;
        }
        String digits = nit.replaceAll("\\D", "");
        if (digits.length() >= 14) {
            return digits.substring(digits.length() - 14);
        }
        return StringUtils.leftPad(digits, 14, '0');
    }
}
