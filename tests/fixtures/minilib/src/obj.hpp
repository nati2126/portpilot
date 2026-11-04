#pragma once
#include <memory>

/* A C++ method named clone() is not Linux clone(2). */
class Obj {
public:
	virtual ~Obj() = default;
	virtual std::unique_ptr<Obj> clone() const;
};
