#include <unistd.h>

int main(void)
{
	return fork() < 0;
}
