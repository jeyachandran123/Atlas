"""A small async client for Chroma Cloud's REST API (v2).

chromadb is pinned at 0.5.20 because the local server is 0.5.20, and that
client cannot use Chroma Cloud: its async client never sends the API token,
and neither of its clients can read the newer server's collection records.
This speaks the documented REST API directly and offers the same awaitable
calls the two vector stores make — get_or_create_collection, get_collection,
delete_collection and, on a collection, upsert / query / get / delete /
count — so neither store knows which kind of server it is talking to.

Collections are created with the stores' ``{"hnsw:space": "cosine"}``
metadata as before; Chroma Cloud maps that onto its own index with cosine
distance, which the stores' ``1 - distance`` scores depend on.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

_QUERY_INCLUDE = ["metadatas", "documents", "distances"]
_GET_INCLUDE = ["metadatas", "documents"]


class ChromaCloudError(Exception):
    """Chroma Cloud refused or failed a call. Carries the status, never the key."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


def _payload(**fields: Any) -> dict[str, Any]:
    """The request body without its unset fields; the API treats absent and null differently."""
    return {k: v for k, v in fields.items() if v is not None}


def _reason(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        text = body.get("message") or body.get("error") or resp.text
    except ValueError:
        text = resp.text
    return " ".join(str(text).split())[:200]


class ChromaCloudCollection:
    """One collection, addressed by id as the API requires."""

    def __init__(self, client: "ChromaCloudClient", record: dict[str, Any]) -> None:
        self._client = client
        self.id: str = record["id"]
        self.name: str = record["name"]
        self.metadata: Optional[dict[str, Any]] = record.get("metadata")

    def _path(self, op: str) -> str:
        return f"{self._client.collections_path}/{self.id}/{op}"

    async def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: Optional[list[str]] = None,
        metadatas: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        await self._client.request("POST", self._path("upsert"), _payload(
            ids=list(ids), embeddings=embeddings, documents=documents, metadatas=metadatas,
        ))

    async def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int = 10,
        where: Optional[dict[str, Any]] = None,
        where_document: Optional[dict[str, Any]] = None,
        include: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        return await self._client.request("POST", self._path("query"), _payload(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where or None,  # an empty filter is sent as no filter
            where_document=where_document or None,
            include=list(include) if include is not None else _QUERY_INCLUDE,
        ))

    async def get(
        self,
        ids: Optional[list[str]] = None,
        where: Optional[dict[str, Any]] = None,
        where_document: Optional[dict[str, Any]] = None,
        include: Optional[list[str]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> dict[str, Any]:
        return await self._client.request("POST", self._path("get"), _payload(
            ids=list(ids) if ids is not None else None,
            where=where or None,
            where_document=where_document or None,
            include=list(include) if include is not None else _GET_INCLUDE,
            limit=limit,
            offset=offset,
        ))

    async def delete(
        self,
        ids: Optional[list[str]] = None,
        where: Optional[dict[str, Any]] = None,
        where_document: Optional[dict[str, Any]] = None,
    ) -> None:
        await self._client.request("POST", self._path("delete"), _payload(
            ids=list(ids) if ids is not None else None,
            where=where or None,
            where_document=where_document or None,
        ))

    async def count(self) -> int:
        return int(await self._client.request("GET", self._path("count")))


class ChromaCloudClient:
    """The client-level calls the vector stores make, against one tenant and database."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        ssl: bool,
        tenant: str,
        database: str,
        api_key: str,
        timeout: float = 30.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        scheme = "https" if ssl else "http"
        self._http = httpx.AsyncClient(
            base_url=f"{scheme}://{host}:{port}",
            headers={"x-chroma-token": api_key},
            timeout=timeout,
            transport=transport,
        )
        self.collections_path = f"/api/v2/tenants/{quote(tenant, safe='')}/databases/{quote(database, safe='')}/collections"

    async def request(self, method: str, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        try:
            resp = await self._http.request(method, path, json=json)
        except httpx.HTTPError as e:
            raise ChromaCloudError(f"Chroma Cloud could not be reached ({type(e).__name__})") from e
        if resp.status_code >= 400:
            raise ChromaCloudError(
                f"Chroma Cloud {method} …/{path.rsplit('/', 1)[-1]} failed with HTTP "
                f"{resp.status_code}: {_reason(resp)}",
                status=resp.status_code,
            )
        return resp.json() if resp.content else None

    def _named(self, name: str) -> str:
        return f"{self.collections_path}/{quote(name, safe='')}"

    async def heartbeat(self) -> int:
        return int((await self.request("GET", "/api/v2/heartbeat"))["nanosecond heartbeat"])

    async def get_or_create_collection(
        self, name: str, metadata: Optional[dict[str, Any]] = None,
    ) -> ChromaCloudCollection:
        record = await self.request("POST", self.collections_path, _payload(
            name=name, metadata=metadata or None, get_or_create=True,
        ))
        return ChromaCloudCollection(self, record)

    async def get_collection(self, name: str) -> ChromaCloudCollection:
        return ChromaCloudCollection(self, await self.request("GET", self._named(name)))

    async def delete_collection(self, name: str) -> None:
        await self.request("DELETE", self._named(name))

    async def list_collections(self) -> list[str]:
        return [c["name"] for c in (await self.request("GET", self.collections_path) or [])]

    async def aclose(self) -> None:
        await self._http.aclose()
