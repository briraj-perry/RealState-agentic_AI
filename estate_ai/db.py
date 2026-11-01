"""MongoDB documents and short atomic commits with optimistic revision checks.

No database transaction is held open while waiting for model/network calls.
MongoDB Atlas or a replica set is required, including in local development.
"""

import copy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from estate_ai.document_query import Count, Field, func, load_only, object_session, or_, select  # noqa: F401


def now():
    return datetime.now(UTC).timestamp()


def uid():
    return uuid4().hex


class ConcurrentWriteError(Exception):
    """A read became stale; reload before trying the operation again."""


class Record:
    pk = "id"

    def __init__(self, **values):
        fields = self.fields()
        if set(values) - fields.keys():
            raise TypeError("Unknown document field")
        for key, field in fields.items():
            default = field.default() if callable(field.default) else field.default
            setattr(self, key, values.get(key, copy.deepcopy(default)))
        self._session = None

    @classmethod
    def fields(cls):
        return {key: value for key, value in vars(cls).items() if isinstance(value, Field)}

    def values(self):
        return {key: getattr(self, key) for key in self.fields()}


class Customer(Record):
    collection, pk = "customers", "phone"
    phone, name = Field(), Field("")
    paused, opted_out, last_inbound = Field(False), Field(False), Field(0)


class Message(Record):
    collection = "messages"
    id, phone, role, content, created = Field(), Field(), Field(), Field(), Field(now)


class TestSession(Record):
    collection, pk = "test_sessions", "phone"
    phone, name, created = Field(), Field(), Field(now)


class Property(Record):
    collection = "properties"
    id, title, city = Field(), Field(), Field()
    locality, bedrooms, asking_price = Field(""), Field(), Field()
    available, verified_at, description, demo = Field(True), Field(now), Field(""), Field(False)


class PropertyPhoto(Record):
    collection = "property_photos"
    id, property_id, data, digest, created = Field(uid), Field(), Field(b""), Field(), Field(now)


class PropertyMetadata(Record):
    collection, pk = "property_metadata", "property_id"
    property_id, payload = Field(), Field()


class InventoryImport(Record):
    collection = "inventory_imports"
    id, filename, payload = Field(uid), Field(), Field()
    status, created = Field("uploaded"), Field(now)


class Proposal(Record):
    collection = "proposals"
    id, phone, kind, payload = Field(uid), Field(), Field(), Field()
    source_message_id, confirmation_message_id = Field(), Field(None)
    status, created = Field("pending_confirmation"), Field(now)


class Job(Record):
    collection = "jobs"
    id, phone, text, channel = Field(), Field(), Field(), Field()
    state, attempts, next_attempt, error, created = (
        Field("pending"),
        Field(0),
        Field(now),
        Field(""),
        Field(now),
    )


class Outbox(Record):
    collection = "outbox"
    id, phone, body, channel = Field(), Field(), Field(), Field()
    state, provider_id, error, created = Field("pending"), Field(""), Field(""), Field(now)


class Audit(Record):
    collection = "audit"
    id, phone, action, detail, created = Field(uid), Field(), Field(), Field(""), Field(now)


MODELS = (
    Customer,
    Message,
    TestSession,
    Property,
    PropertyPhoto,
    PropertyMetadata,
    InventoryImport,
    Proposal,
    Job,
    Outbox,
    Audit,
)


class MongoUnitOfWork:
    def __init__(self, factory):
        self.factory = factory
        self.records, self.originals, self.revisions = {}, {}, {}
        self.guarded, self.deleted = set(), set()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.rollback()

    def _key(self, model, identity):
        return model, str(identity)

    def _load(self, model, document):
        key = self._key(model, document["_id"])
        if key not in self.records:
            record = model(**{k: v for k, v in document.items() if k in model.fields()})
            record._session = self
            self.records[key] = record
            self.originals[key] = copy.deepcopy(record.values())
            self.revisions[key] = document.get("_revision", 0)
        return self.records[key]

    def get(self, model, identity):
        key = self._key(model, identity)
        if key in self.deleted:
            return None
        if key in self.records:
            return self.records[key]
        document = self.factory.database[model.collection].find_one({"_id": str(identity)})
        return self._load(model, document) if document else None

    def add(self, record):
        identity = getattr(record, record.pk)
        if identity is None:
            raise ValueError("Document requires an identity")
        key = self._key(type(record), identity)
        if key in self.records and self.records[key] is not record:
            raise DuplicateKeyError("Duplicate document identity")
        record._session = self
        self.records[key] = record
        self.originals.setdefault(key, None)
        self.revisions.setdefault(key, 0)

    def delete(self, record):
        self.deleted.add(self._key(type(record), getattr(record, record.pk)))

    def flush(self):
        # Defaults/IDs are assigned at construction; writes wait until atomic commit.
        pass

    def scalars(self, query):
        model = query.model
        projection = None
        if query.projection:
            filter_names = [
                key for condition in query.conditions for key in condition.mongo if not key.startswith("$")
            ]
            projection = {name: 1 for name in [*query.projection, *filter_names, model.pk, "_revision"]}
        cursor = self.factory.database[model.collection].find(query.filter, projection)
        if query.sort:
            cursor = cursor.sort(query.sort)
        if query.maximum is not None:
            cursor = cursor.limit(query.maximum + len(self.records) + 1)
        rows = {str(doc["_id"]): self._load(model, doc) for doc in cursor}
        rows.update({identity: row for (kind, identity), row in self.records.items() if kind is model})
        result = [
            row
            for identity, row in rows.items()
            if (model, identity) not in self.deleted
            and all(c.matches(row.values()) for c in query.conditions)
        ]
        for name, direction in reversed(query.sort):
            result.sort(key=lambda row: getattr(row, name), reverse=direction < 0)
        if query.maximum is not None:
            result = result[: query.maximum]
        if query.guard:
            self.guarded.update(self._key(model, getattr(row, model.pk)) for row in result)
        return (
            [getattr(row, query.target.name) for row in result] if isinstance(query.target, Field) else result
        )

    def scalar(self, query):
        if isinstance(query.target, Count):
            if not any(kind is query.model for kind, _ in self.records):
                return self.factory.database[query.model.collection].count_documents(query.filter)
            return len(self.scalars(query))
        rows = self.scalars(query.limit(1))
        return rows[0] if rows else None

    def refresh(self, record):
        key = self._key(type(record), getattr(record, record.pk))
        original = self.originals[key]
        changes = {k: v for k, v in record.values().items() if v != original[k]}
        document = self.factory.database[record.collection].find_one({"_id": key[1]})
        if not document:
            raise ConcurrentWriteError("Document was removed")
        for name in record.fields():
            setattr(record, name, document[name])
        self.originals[key] = copy.deepcopy(record.values())
        self.revisions[key] = document["_revision"]
        for name, value in changes.items():
            setattr(record, name, value)

    def commit(self):
        writes = []
        for key, record in self.records.items():
            current, original = record.values(), self.originals[key]
            changes = current if original is None else {k: v for k, v in current.items() if v != original[k]}
            if changes or key in self.guarded or key in self.deleted:
                writes.append((key, current, changes, original))
        if not writes:
            return

        def save(mongo_session):
            for (model, identity), current, changes, original in writes:
                collection = self.factory.database[model.collection]
                key = model, identity
                if original is None:
                    if key not in self.deleted:
                        collection.insert_one(
                            {"_id": identity, "_revision": 1, **current}, session=mongo_session
                        )
                else:
                    match = {"_id": identity, "_revision": self.revisions[key]}
                    if key in self.deleted:
                        result = collection.delete_one(match, session=mongo_session)
                        matched = result.deleted_count
                    else:
                        result = collection.update_one(
                            match, {"$set": changes, "$inc": {"_revision": 1}}, session=mongo_session
                        )
                        matched = result.matched_count
                    if not matched:
                        raise ConcurrentWriteError("Data changed; reload before retrying")

        with self.factory.client.start_session() as mongo_session:
            mongo_session.with_transaction(
                save, read_concern=ReadConcern("snapshot"), write_concern=WriteConcern("majority")
            )
        for key, current, _, original in writes:
            self.originals[key] = copy.deepcopy(current)
            self.revisions[key] = 1 if original is None else self.revisions[key] + 1
        for key in self.deleted:
            self.records.pop(key, None)
            self.originals.pop(key, None)
            self.revisions.pop(key, None)
        self.deleted.clear()
        self.guarded.clear()

    def rollback(self):
        for key, record in list(self.records.items()):
            original = self.originals[key]
            if original is None:
                record._session = None
                self.records.pop(key)
                self.originals.pop(key)
                self.revisions.pop(key)
            else:
                for name, value in original.items():
                    setattr(record, name, copy.deepcopy(value))
        self.guarded.clear()
        self.deleted.clear()


class WorkerLease:
    def __init__(self, database):
        self.collection, self.owner = database["worker_leases"], uid()

    def acquire(self):
        timestamp = datetime.now(UTC)
        try:
            row = self.collection.find_one_and_update(
                {"_id": "worker", "$or": [{"expires_at": {"$lte": timestamp}}, {"owner": self.owner}]},
                {"$set": {"owner": self.owner, "expires_at": timestamp + timedelta(seconds=90)}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            return row["owner"] == self.owner
        except DuplicateKeyError:
            return False

    def renew(self):
        timestamp = datetime.now(UTC)
        return (
            self.collection.update_one(
                {"_id": "worker", "owner": self.owner, "expires_at": {"$gt": timestamp}},
                {"$set": {"expires_at": timestamp + timedelta(seconds=90)}},
            ).matched_count
            == 1
        )

    def release(self):
        self.collection.delete_one({"_id": "worker", "owner": self.owner})


class MongoFactory:
    def __init__(self, uri, name="estate_ai"):
        self.client = MongoClient(
            uri, serverSelectionTimeoutMS=10000, connectTimeoutMS=10000, socketTimeoutMS=15000
        )
        self.database = self.client[name]
        hello = self.client.admin.command("hello")
        if not hello.get("setName") and hello.get("msg") != "isdbgrid":
            self.client.close()
            raise ValueError("MongoDB requires a replica set or Atlas cluster for atomic transactions")
        for model in MODELS:
            self.database[model.collection].create_index([(model.pk, 1)], unique=True)
        for model in (Message, Proposal, Job, Outbox, Audit):
            self.database[model.collection].create_index([("phone", 1), ("created", -1)])
        for model in (Job, Outbox):
            self.database[model.collection].create_index([("state", 1), ("created", 1)])
        self.database[PropertyPhoto.collection].create_index([("property_id", 1), ("digest", 1)], unique=True)
        self.database[Property.collection].create_index(
            [("available", 1), ("demo", 1), ("asking_price", 1), ("id", 1)]
        )
        self.database[Audit.collection].create_index([("phone", 1), ("action", 1), ("created", -1)])

    def __call__(self):
        return MongoUnitOfWork(self)

    def lease(self):
        return WorkerLease(self.database)

    def close(self):
        self.client.close()


def connect(uri, name="estate_ai"):
    return MongoFactory(uri, name)
