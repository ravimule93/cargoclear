"""A small in-process stand-in for the async Firestore client: no network, no credentials.

Only what the repository / audit code uses: ``collection().document().collection()...``, ``get``, ``set``
(optionally merge), ``create`` (raises AlreadyExists), ``update`` (raises NotFound), ``delete``, and
``order_by().limit().stream()`` over a collection. Transactions (``FakeFirestore.transaction()`` with
``fake_async_transactional``, the stand-in for ``google.cloud.firestore_v1.async_transactional``) are OPTIMISTIC like the
real ones: a commit is refused with ``Aborted`` if a document the transaction read has changed since, so interleaved
transactions behave as they do on Firestore. Every operation yields to the event loop once, like the real
client does (the in-memory stores of the app never yield, which hides races).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from google.api_core.exceptions import Aborted, AlreadyExists, NotFound


class FakeSnapshot:
    def __init__(self, path: tuple[str, ...], data: dict[str, Any] | None) -> None:
        self.id = path[-1]
        self.reference_path = path
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)


class FakeQuery:
    def __init__(self, store: "FakeFirestore", path: tuple[str, ...]) -> None:
        self._store, self._path = store, path
        self._order: tuple[str, str] | None = None
        self._limit: int | None = None

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        clone = FakeQuery(self._store, self._path)
        clone._order, clone._limit = (field, direction), self._limit
        return clone

    def limit(self, count: int) -> "FakeQuery":
        clone = FakeQuery(self._store, self._path)
        clone._order, clone._limit = self._order, count
        return clone

    async def stream(self):
        await asyncio.sleep(0)
        self._store.calls.append(("stream", self._path))
        rows = [
            (path, data)
            for path, data in self._store.docs.items()
            if len(path) == len(self._path) + 1 and path[: len(self._path)] == self._path
        ]
        if self._order:
            field, direction = self._order
            rows.sort(key=lambda row: row[1].get(field), reverse=direction == "DESCENDING")
        if self._limit is not None:
            rows = rows[: self._limit]
        for path, data in rows:
            yield FakeSnapshot(path, data)


class FakeCollection(FakeQuery):
    def document(self, doc_id: str) -> "FakeDocument":
        return FakeDocument(self._store, self._path + (doc_id,))


class FakeDocument:
    def __init__(self, store: "FakeFirestore", path: tuple[str, ...]) -> None:
        self._store, self._path = store, path

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._store, self._path + (name,))

    async def get(self, transaction: "FakeTransaction | None" = None) -> FakeSnapshot:
        await asyncio.sleep(0)
        self._store.calls.append(("get", self._path))
        if transaction is not None:
            transaction.reads[self._path] = self._store.versions.get(self._path, 0)
        data = self._store.docs.get(self._path)
        return FakeSnapshot(self._path, None if data is None else dict(data))

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("set", self._path))
        if merge and self._path in self._store.docs:
            self._store.docs[self._path].update(data)
        else:
            self._store.docs[self._path] = dict(data)
        self._store.bump(self._path)

    async def create(self, data: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("create", self._path))
        if self._store.before_create is not None:
            self._store.before_create(self._path, data)
        if self._path in self._store.docs:
            raise AlreadyExists(f"document {'/'.join(self._path)} already exists")
        self._store.docs[self._path] = dict(data)
        self._store.bump(self._path)

    async def delete(self) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("delete", self._path))
        self._store.docs.pop(self._path, None)
        self._store.bump(self._path)

    async def update(self, data: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("update", self._path))
        if self._path not in self._store.docs:
            raise NotFound(f"document {'/'.join(self._path)} does not exist")
        self._store.docs[self._path].update(data)
        self._store.bump(self._path)


class FakeTransaction:
    """Buffers writes; ``commit`` applies them atomically, or raises ``Aborted`` if something it read has changed."""

    def __init__(self, store: "FakeFirestore", max_attempts: int = 5) -> None:
        self._store = store
        self.max_attempts = max_attempts
        self.reads: dict[tuple[str, ...], int] = {}
        self._writes: list[tuple[str, tuple[str, ...], dict[str, Any] | None]] = []

    def _path(self, ref: FakeDocument) -> tuple[str, ...]:
        return ref._path

    def set(self, ref: FakeDocument, data: dict[str, Any], merge: bool = False) -> None:
        self._writes.append(("merge" if merge else "set", self._path(ref), dict(data)))

    def create(self, ref: FakeDocument, data: dict[str, Any]) -> None:
        self._writes.append(("create", self._path(ref), dict(data)))

    def update(self, ref: FakeDocument, data: dict[str, Any]) -> None:
        self._writes.append(("update", self._path(ref), dict(data)))

    def delete(self, ref: FakeDocument) -> None:
        self._writes.append(("delete", self._path(ref), None))

    def clean_up(self) -> None:
        self.reads.clear()
        self._writes.clear()

    async def commit(self) -> None:
        await asyncio.sleep(0)
        store = self._store
        store.calls.append(("commit", ()))
        for path, version in self.reads.items():
            if store.versions.get(path, 0) != version:
                raise Aborted("the documents read by the transaction changed")
        for kind, path, data in self._writes:  # all-or-nothing: validate before applying
            if kind == "create" and path in store.docs:
                raise AlreadyExists(f"document {'/'.join(path)} already exists")
            if kind == "update" and path not in store.docs:
                raise NotFound(f"document {'/'.join(path)} does not exist")
        for kind, path, data in self._writes:
            if kind == "delete":
                store.docs.pop(path, None)
            elif kind == "update":
                store.docs[path].update(data or {})
            elif kind == "merge":
                store.docs.setdefault(path, {}).update(data or {})
            else:
                store.docs[path] = dict(data or {})
            store.bump(path)


def fake_async_transactional(to_wrap: Callable[..., Any]) -> Callable[..., Any]:
    """The stand-in for ``google.cloud.firestore_v1.async_transactional``: run, commit, retry on ``Aborted`` (5 attempts)."""

    async def run(transaction: FakeTransaction, *args: Any, **kwargs: Any) -> Any:
        last: Exception | None = None
        for _attempt in range(transaction.max_attempts):
            transaction.clean_up()
            result = await to_wrap(transaction, *args, **kwargs)
            try:
                await transaction.commit()
                return result
            except Aborted as exc:
                last = exc
        raise ValueError(f"Failed to commit transaction in {transaction.max_attempts} attempts.") from last

    return run


class FakeFirestore:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, ...], dict[str, Any]] = {}
        self.versions: dict[tuple[str, ...], int] = {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        # called as before_create(path, data) inside every create(); a test uses it to play "the other writer"
        self.before_create: Callable[[tuple[str, ...], dict[str, Any]], None] | None = None

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def transaction(self, max_attempts: int = 5) -> FakeTransaction:
        return FakeTransaction(self, max_attempts)

    def bump(self, path: tuple[str, ...]) -> None:
        self.versions[path] = self.versions.get(path, 0) + 1

    def where_calls(self, kind: str) -> list[tuple[str, ...]]:
        return [path for call, path in self.calls if call == kind]
