#include "obj.hpp"

std::unique_ptr<Obj> Obj::clone() const
{
	return std::make_unique<Obj>(*this);
}

std::unique_ptr<Obj> copy(const Obj &o)
{
	auto c = o.clone();
	return c;
}
