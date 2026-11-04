#include "platform.h"

#if MINI_OS == MINI_OS_WIN
#include <windows.h>
#endif

#if MINI_USE_FANCY
#include <fancy/fancy.h>
#endif

#if __has_include(<xlocale.h>)
#include <xlocale.h>
#endif

int mini_os(void)
{
	return MINI_OS;
}
