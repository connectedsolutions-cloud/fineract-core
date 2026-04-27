package org.apache.fineract.portfolio.invoice.mh;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;

class NitNormalizerTest {

    @Test
    void padsToFourteenDigits() {
        assertEquals("00000006140101", NitNormalizer.toFourteenDigits("6140101"));
    }

    @Test
    void stripsNonDigits() {
        assertEquals("06140101901021", NitNormalizer.toFourteenDigits("0614-0101-9010-21"));
    }

    @Test
    void nullReturnsNull() {
        assertNull(NitNormalizer.toFourteenDigits(null));
        assertNull(NitNormalizer.toFourteenDigits("   "));
    }
}
