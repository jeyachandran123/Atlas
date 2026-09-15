"""The one Chroma connection both vector stores use: local as before, Chroma Cloud over its REST API."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

import app.vector_store.chroma_client as cc
from app.vector_store.chroma_cloud import ChromaCloudClient, ChromaCloudError

COLL = "/api/v2/tenants/t1/databases/db1/collections"
RECORD = {"id": "c-1", "name": "dip_default", "metadata": {"hnsw:space": "cosine"}}


def cloud(handler) -> ChromaCloudClient:
    return ChromaCloudClient(
        host="api.trychroma.com", port=443, ssl=True, tenant="t1", database="db1",
        api_key="ck-test", transport=httpx.MockTransport(handler),
    )


async def test_a_collection_is_created_once_then_addressed_by_id():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("x-chroma-token"),
                     json.loads(req.content) if req.content else None))
        path = req.url.path
        if path == COLL:
            return httpx.Response(200, json=RECORD)
        if path.endswith("/upsert"):
            return httpx.Response(200, json={})
        if path.endswith("/count"):
            return httpx.Response(200, json=2)
        if path.endswith("/query"):
            return httpx.Response(200, json={
                "ids": [["a"]], "documents": [["dosa"]], "metadatas": [[{"state": "TN"}]],
                "distances": [[0.01]], "include": ["documents", "metadatas", "distances"],
            })
        return httpx.Response(404, json={"error": "NotFound", "message": "no such route"})

    coll = await cloud(handler).get_or_create_collection(name="dip_default", metadata={"hnsw:space": "cosine"})
    await coll.upsert(ids=["a", "b"], embeddings=[[1.0, 0.0], [0.0, 1.0]],
                      documents=["dosa", "appam"], metadatas=[{"state": "TN"}, {"state": "KL"}])
    assert await coll.count() == 2
    hits = await coll.query(query_embeddings=[[0.9, 0.1]], n_results=1, where={"state": {"$eq": "TN"}})
    assert hits["ids"][0] == ["a"]

    create, upsert, count, query = seen
    assert create[:2] == ("POST", COLL)
    assert create[3] == {"name": "dip_default", "metadata": {"hnsw:space": "cosine"}, "get_or_create": True}
    assert upsert[1] == f"{COLL}/c-1/upsert" and upsert[3]["ids"] == ["a", "b"]
    assert count[:2] == ("GET", f"{COLL}/c-1/count")
    assert query[3] == {"query_embeddings": [[0.9, 0.1]], "n_results": 1,
                        "where": {"state": {"$eq": "TN"}},
                        "include": ["metadatas", "documents", "distances"]}
    assert {s[2] for s in seen} == {"ck-test"}  # every call carries the key


async def test_an_empty_filter_is_left_out_rather_than_sent():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == f"{COLL}/dip_default":
            return httpx.Response(200, json=RECORD)
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"ids": [[]], "include": []})

    coll = await cloud(handler).get_collection("dip_default")
    await coll.query(query_embeddings=[[1.0]], n_results=3, where={})
    assert "where" not in bodies[0]


async def test_deleting_a_collection_addresses_it_by_name():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={})

    await cloud(handler).delete_collection("dip_default")
    assert seen == [("DELETE", f"{COLL}/dip_default")]


async def test_a_refusal_is_an_error_with_its_status_and_never_the_key():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "ChromaError", "message": "Permission denied."})

    with pytest.raises(ChromaCloudError) as caught:
        await cloud(handler).get_collection("dip_default")
    assert caught.value.status == 403
    assert "Permission denied" in str(caught.value)
    assert "ck-test" not in str(caught.value)


@pytest.fixture
def chroma_cfg(monkeypatch):
    def configure(**values):
        for key, value in values.items():
            monkeypatch.setattr(cc.cfg, key, value)
    return configure


async def test_an_api_key_connects_to_chroma_cloud(chroma_cfg):
    chroma_cfg(chroma_api_key=SecretStr("ck-test"), chroma_host="api.trychroma.com",
               chroma_port=443, chroma_ssl=True, chroma_tenant="t1", chroma_database="db1")

    client = await cc.connect_chroma()
    try:
        assert isinstance(client, ChromaCloudClient)
        # httpx drops the default :443 from an https address.
        assert str(client._http.base_url) == "https://api.trychroma.com"
        assert client.collections_path == COLL
    finally:
        await client.aclose()


async def test_no_api_key_keeps_the_plain_local_connection(monkeypatch, chroma_cfg):
    # Empty tenant / database lines in a .env mean "use the defaults".
    chroma_cfg(chroma_api_key=SecretStr(""), chroma_host="localhost", chroma_port=8001, chroma_ssl=False,
               chroma_tenant="", chroma_database="")
    seen: dict = {}

    async def fake_async_client(**kwargs):
        seen.update(kwargs)
        return "native"

    monkeypatch.setattr(cc.chromadb, "AsyncHttpClient", fake_async_client)

    assert await cc.connect_chroma() == "native"
    assert (seen["host"], seen["port"], seen["ssl"]) == ("localhost", 8001, False)
    assert (seen["tenant"], seen["database"]) == ("default_tenant", "default_database")
