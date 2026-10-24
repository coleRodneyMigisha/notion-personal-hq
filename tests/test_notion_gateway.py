"""The real gateway, exercised against a mocked notion-client SDK (no network)."""
from types import SimpleNamespace

import httpx
import pytest
from notion_client.errors import APIResponseError

from personal_hq.notion_api import NotionError, NotionGateway


class FakeEndpoint:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        index = int(kwargs.get("start_cursor") or 0)
        last = index == len(self.pages) - 1
        return {"results": self.pages[index], "has_more": not last, "next_cursor": None if last else str(index + 1)}


def gateway_with(**endpoints):
    client = SimpleNamespace(
        blocks=SimpleNamespace(children=SimpleNamespace(list=endpoints.get("children"), append=endpoints.get("append"))),
        pages=SimpleNamespace(retrieve=endpoints.get("retrieve"), create=endpoints.get("create")),
        data_sources=SimpleNamespace(query=endpoints.get("query")),
        views=SimpleNamespace(create=endpoints.get("view_create")),
    )
    return NotionGateway("unused", client=client, min_interval=0)


def test_pagination_follows_cursors():
    endpoint = FakeEndpoint([[{"id": 1}, {"id": 2}], [{"id": 3}], [{"id": 4}]])
    gw = gateway_with(query=endpoint)
    assert [r["id"] for r in gw.query_data_source("ds", {"property": "x"})] == [1, 2, 3, 4]
    assert [c.get("start_cursor") for c in endpoint.calls] == [None, "1", "2"]
    assert all(c["page_size"] == 100 and c["data_source_id"] == "ds" for c in endpoint.calls)


def _api_error(status, code):
    return APIResponseError(code=code, status=status, message="nope", headers=httpx.Headers(), raw_body_text="{}")


@pytest.mark.parametrize("status,code,hint", [
    (404, "object_not_found", "Connections"),
    (401, "unauthorized", "token"),
    (403, "restricted_resource", "capability"),
    (429, "rate_limited", "rerun"),
    (400, "validation_error", "request shape"),
])
def test_api_errors_become_actionable(status, code, hint):
    def boom(**_):
        raise _api_error(status, code)
    gw = gateway_with(retrieve=boom)
    with pytest.raises(NotionError) as info:
        gw.retrieve_page("x")
    assert info.value.status == status
    assert hint in info.value.hint


def test_network_errors_are_wrapped():
    def offline(**_):
        raise httpx.ConnectError("no route")
    gw = gateway_with(retrieve=offline)
    with pytest.raises(NotionError) as info:
        gw.retrieve_page("x")
    assert info.value.status == 0 and "Network" in info.value.hint


def test_write_bodies_pass_through_unchanged():
    seen = {}
    gw = gateway_with(append=lambda **kw: seen.update(kw) or {"results": []},
                      view_create=lambda **kw: seen.update(view=kw) or {"id": "v"})
    gw.append_children("page", [{"type": "divider", "divider": {}}], {"type": "end"})
    gw.create_view({"name": "Today", "create_database": {"parent": {"page_id": "p"}}})
    assert seen["block_id"] == "page" and seen["position"] == {"type": "end"}
    assert seen["view"]["create_database"]["parent"]["page_id"] == "p"
