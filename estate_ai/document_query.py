"""Typed MongoDB filters owned by the server, never arbitrary model expressions."""

import copy
import re


class Condition:
    def __init__(self, mongo, predicate):
        self.mongo, self.matches = mongo, predicate


def or_(*conditions):
    return Condition(
        {"$or": [c.mongo for c in conditions]}, lambda row: any(c.matches(row) for c in conditions)
    )


class Field:
    def __init__(self, default=None):
        self.default = default

    def __set_name__(self, owner, name):
        self.owner, self.name = owner, name

    def __get__(self, instance, owner):
        return self if instance is None else instance.__dict__[self.name]

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value

    def __eq__(self, value):
        return Condition({self.name: value}, lambda row: row.get(self.name) == value)

    def __le__(self, value):
        return Condition({self.name: {"$lte": value}}, lambda row: row[self.name] <= value)

    def is_(self, value):
        return self == value

    def in_(self, values):
        values = list(values)
        return Condition({self.name: {"$in": values}}, lambda row: row.get(self.name) in values)

    def not_in(self, values):
        values = list(values)
        return Condition({self.name: {"$nin": values}}, lambda row: row.get(self.name) not in values)

    def ilike(self, value):
        return self._regex("^" + re.escape(value) + "$")

    def icontains(self, value, autoescape=True):
        return self._regex(re.escape(value))

    def _regex(self, pattern):
        expression = re.compile(pattern, re.IGNORECASE)
        return Condition({self.name: expression}, lambda row: bool(expression.search(row.get(self.name, ""))))

    def desc(self):
        return self, -1


class Count:
    pass


class func:
    count = Count


class Query:
    def __init__(self, target):
        self.target = target
        self.model = target.owner if isinstance(target, Field) else target
        self.conditions, self.sort = [], []
        self.maximum, self.projection, self.guard = None, None, False

    def where(self, *conditions):
        result = copy.copy(self)
        result.conditions = self.conditions + list(conditions)
        return result

    def order_by(self, *fields):
        result = copy.copy(self)
        result.sort = [
            (f.name, direction) for f, direction in (x if isinstance(x, tuple) else (x, 1) for x in fields)
        ]
        return result

    def limit(self, value):
        result = copy.copy(self)
        result.maximum = value
        return result

    def select_from(self, model):
        result = copy.copy(self)
        result.model = model
        return result

    def options(self, projection):
        result = copy.copy(self)
        result.projection = projection
        return result

    def with_for_update(self):
        # MongoDB optimistic revision check replaces SQL row locking.
        result = copy.copy(self)
        result.guard = True
        return result

    @property
    def filter(self):
        return {"$and": [c.mongo for c in self.conditions]} if self.conditions else {}


def select(target):
    return Query(target)


def load_only(*fields):
    return [f.name for f in fields]


def object_session(record):
    return getattr(record, "_session", None)
