/* F-015: does strtod round-trip doubles exactly, including subnormals?
 * Prints each value, the bits strtod returns and the bits expected. Build it twice: against
 * QNX libc, and linked with muslflt (the official QNX port of musl's float code). */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint64_t bits(double d) { uint64_t u; memcpy(&u, &d, sizeof u); return u; }

int main(void) {
    static const struct { const char *s; uint64_t want; } cases[] = {
        {"2.2250738585072009e-308", 0x000FFFFFFFFFFFFFull}, /* largest subnormal */
        {"4.9406564584124654e-324", 0x0000000000000001ull}, /* smallest subnormal */
        {"2.2250738585072014e-308", 0x0010000000000000ull}, /* smallest normal */
        {"1.0000000000000002", 0x3FF0000000000001ull},      /* 1 + 1 ulp */
        {"0.1", 0x3FB999999999999Aull},
        {"1.7976931348623157e308", 0x7FEFFFFFFFFFFFFFull},  /* largest double */
    };
    int bad = 0;
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        uint64_t got = bits(strtod(cases[i].s, NULL));
        int ok = got == cases[i].want;
        bad += !ok;
        printf("%-26s got %016llx want %016llx %s\n", cases[i].s, (unsigned long long)got,
               (unsigned long long)cases[i].want, ok ? "ok" : "WRONG");
    }
    printf("%d of %zu wrong\n", bad, sizeof cases / sizeof cases[0]);
    return bad != 0;
}
