/* Optional TLS engine: only with -DMINI_ENABLE_TLS=ON. */
#include <mbedtls/ssl.h>

int mini_tls_init(void)
{
	return 0;
}
