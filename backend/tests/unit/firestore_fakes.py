"""A small in-process stand-in for the async Firestore client: no network, no credentials.

Only what the repository / audit code uses: ``collection().document().collection()...``, ``get``, ``set``
(optionally merge), ``create`` (raises AlreadyExists), ``update`` (raises NotFound), and
``order_by().limit().stream()`` over a collection. Every operation yields to the event loop once, like the real
client does (the in-memory stores of the app never yield, which hides races).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from google.api_core.exceptions import AlreadyExists, NotFound


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

    async def get(self) -> FakeSnapshot:
        await asyncio.sleep(0)
        self._store.calls.append(("get", self._path))
        data = self._store.docs.get(self._path)
        return FakeSnapshot(self._path, None if data is None else dict(data))

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("set", self._path))
        if merge and self._path in self._store.docs:
            self._store.docs[self._path].update(data)
        else:
            self._store.docs[self._path] = dict(data)

    async def create(self, data: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("create", self._path))
        if self._store.before_create is not None:
            self._store.before_create(self._path, data)
        if self._path in self._store.docs:
            raise AlreadyExists(f"document {'/'.join(self._path)} already exists")
        self._store.docs[self._path] = dict(data)

    async def update(self, data: dict[str, Any]) -> None:
        await asyncio.sleep(0)
        self._store.calls.append(("update", self._path))
        if self._path not in self._store.docs:
            raise NotFound(f"document {'/'.join(self._path)} does not exist")
        self._store.docs[self._path].update(data)


class FakeFirestore:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, ...], dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        # called as before_create(path, data) inside every create(); a test uses it to play "the other writer"
        self.before_create: Callable[[tuple[str, ...], dict[str, Any]], None] | None = None

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, (name,))

    def where_calls(self, kind: str) -> list[tuple[str, ...]]:
        return [path for call, path in self.calls if call == kind]
