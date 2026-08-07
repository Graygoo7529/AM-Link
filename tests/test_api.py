from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aml_memory.api import create_app
from aml_memory.projection import user_scope_hash
from aml_memory.repository import _query_tokens, stable_memory_id
from aml_memory.settings import Settings


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "db_path": tmp_path / "memory.db",
        "markdown_view_dir": tmp_path / "markdown",
        "auth_scheme": "none",
        "api_key": "",
        "max_top_k": 100,
    }
    values.update(overrides)
    return Settings(**values)


def add_payload(
    *,
    user_id: str = "run-1:user-1",
    request_id: str = "run-1:chunk-1",
    content: str = "I will visit Shanghai next Monday.",
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "messages": [
            {
                "role": "user",
                "timestamp": 1_704_067_200_000,
                "content": content,
            }
        ],
        "user_id": user_id,
        "session_id": "run-1:session-1",
    }


def test_query_tokens_prioritize_content_terms() -> None:
    assert _query_tokens("What did Caroline study at the university?") == [
        "caroline",
        "study",
        "university",
    ]


def search_payload(
    *, user_id: str = "run-1:user-1", query: str = "Shanghai", top_k: int = 100
) -> dict[str, object]:
    return {
        "query": query,
        "options": ["Shanghai", "Beijing"],
        "user_id": user_id,
        "top_k": top_k,
    }


def test_health_is_unauthenticated(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path, auth_scheme="bearer", api_key="memory-secret"
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_add_is_immediately_searchable_and_projects_markdown(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    payload = add_payload()

    with TestClient(create_app(settings)) as client:
        add_response = client.post("/v1/memory/add", json=payload)
        search_response = client.post(
            "/v1/memory/search", json=search_payload()
        )

    assert add_response.status_code == 200
    assert add_response.json() == {
        "success": True,
        "request_id": payload["request_id"],
        "user_id": payload["user_id"],
        "session_id": payload["session_id"],
    }
    assert search_response.status_code == 200
    results = search_response.json()["data"]
    assert len(results) == 1
    assert results[0]["id"].startswith("mem_")
    assert "Shanghai" in results[0]["content"]
    assert results[0]["created_at"] == "2024-01-01T00:00:00.000Z"

    user_dir = settings.markdown_view_dir / user_scope_hash(str(payload["user_id"]))
    assert "Shanghai" in (user_dir / "Memory.md").read_text(encoding="utf-8")
    assert "Shanghai" in (user_dir / "daily" / "2024-01-01.md").read_text(
        encoding="utf-8"
    )


def test_add_preserves_opaque_ids_and_message_whitespace(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    payload = add_payload(
        user_id=" user-with-spaces ",
        request_id=" request-with-spaces ",
        content="  preserve this boundary  ",
    )
    with TestClient(create_app(settings)) as client:
        added = client.post("/v1/memory/add", json=payload)
        found = client.post(
            "/v1/memory/search",
            json=search_payload(user_id=payload["user_id"], query="preserve"),
        )

    assert added.status_code == 200
    assert added.json()["request_id"] == payload["request_id"]
    assert added.json()["user_id"] == payload["user_id"]
    assert "  preserve this boundary  " in found.json()["data"][0]["content"]


def test_add_retry_is_idempotent_and_payload_change_conflicts(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    payload = add_payload()

    with TestClient(create_app(settings)) as client:
        first = client.post("/v1/memory/add", json=payload)
        replay = client.post("/v1/memory/add", json=payload)
        changed = client.post(
            "/v1/memory/add",
            json={**payload, "messages": [{"role": "user", "content": "changed"}]},
        )

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert changed.status_code == 409
    assert "request_id" in changed.json()["detail"]["reason"]

    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM add_requests").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 1


def test_search_never_crosses_user_boundary(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/memory/add", json=add_payload()).status_code == 200
        other_user = client.post(
            "/v1/memory/search",
            json=search_payload(user_id="run-2:user-1"),
        )
        owning_user = client.post(
            "/v1/memory/search", json=search_payload()
        )

    assert other_user.status_code == 200
    assert other_user.json() == {"data": []}
    assert len(owning_user.json()["data"]) == 1


def test_search_returns_empty_data_and_honors_top_k(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        for index in range(3):
            response = client.post(
                "/v1/memory/add",
                json=add_payload(
                    request_id=f"run-1:chunk-{index}",
                    content=f"Project Aurora note number {index}",
                ),
            )
            assert response.status_code == 200

        limited = client.post(
            "/v1/memory/search",
            json=search_payload(query="Project Aurora", top_k=2),
        )
        missing = client.post(
            "/v1/memory/search",
            json=search_payload(query="nonexistent-token"),
        )

    assert len(limited.json()["data"]) == 2
    assert missing.json() == {"data": []}


def test_search_options_help_recall_without_becoming_an_answer(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(content="The user's preferred color is cerulean."),
        ).status_code == 200
        response = client.post(
            "/v1/memory/search",
            json={
                "query": "What color does the user prefer?",
                "options": ["cerulean", "vermilion"],
                "user_id": "run-1:user-1",
                "top_k": 100,
            },
        )

    assert response.status_code == 200
    assert "cerulean" in response.json()["data"][0]["content"]


def test_cjk_phrase_search_keeps_entity_and_topic_tokens(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        added = client.post(
            "/v1/memory/add",
            json=add_payload(
                content="我计划下周去上海参加会议。",
                request_id="run:cjk-1",
            ),
        )
        found = client.post(
            "/v1/memory/search",
            json=search_payload(query="上海会议", top_k=5),
        )

    assert added.status_code == found.status_code == 200
    assert found.json()["data"]
    assert "上海" in found.json()["data"][0]["content"]


def test_historical_intent_survives_without_query_planner(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, markdown_view_dir=None)
    payload = add_payload(content="I previously lived in Paris.")
    with TestClient(create_app(settings)) as client:
        assert client.post("/v1/memory/add", json=payload).status_code == 200
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute(
                "UPDATE memory_nodes SET status = 'superseded' WHERE memory_id = ("
                "SELECT memory_id FROM raw_events WHERE request_id = ?)" ,
                (payload["request_id"],),
            )
        current = client.post(
            "/v1/memory/search",
            json=search_payload(query="Where does the user live now?"),
        )
        historical = client.post(
            "/v1/memory/search",
            json=search_payload(query="Where did the user live previously?"),
        )

    assert current.status_code == historical.status_code == 200
    assert current.json() == {"data": []}
    assert historical.json()["data"]
    assert "Paris" in historical.json()["data"][0]["content"]


def test_relative_date_search_uses_latest_source_time_as_anchor(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, markdown_view_dir=None)
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/v1/memory/add",
            json=add_payload(
                request_id="run:relative-date",
                content="I will visit Shanghai next Monday.",
            ),
        ).status_code == 200
        response = client.post(
            "/v1/memory/search",
            json=search_payload(query="What happens next Monday?", top_k=5),
        )

    assert response.status_code == 200
    assert response.json()["data"]
    assert "Shanghai" in response.json()["data"][0]["content"]


@pytest.mark.parametrize(
    ("scheme", "valid_headers", "invalid_headers"),
    [
        ("token", {"Authorization": "Token secret"}, {"Authorization": "Bearer secret"}),
        ("bearer", {"Authorization": "Bearer secret"}, {"Authorization": "Token secret"}),
        ("x-api-key", {"X-Api-Key": "secret"}, {"X-Api-Key": "wrong"}),
    ],
)
def test_supported_authentication_schemes(
    tmp_path: Path,
    scheme: str,
    valid_headers: dict[str, str],
    invalid_headers: dict[str, str],
) -> None:
    settings = make_settings(tmp_path, auth_scheme=scheme, api_key="secret")
    with TestClient(create_app(settings)) as client:
        missing = client.post("/v1/memory/search", json=search_payload())
        invalid = client.post(
            "/v1/memory/search", json=search_payload(), headers=invalid_headers
        )
        valid = client.post(
            "/v1/memory/search", json=search_payload(), headers=valid_headers
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


def test_protocol_validation_rejects_unknown_fields_and_invalid_top_k(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        extra_field = client.post(
            "/v1/memory/add", json={**add_payload(), "async_mode": True}
        )
        invalid_top_k = client.post(
            "/v1/memory/search", json=search_payload(top_k=101)
        )

    assert extra_field.status_code == 422
    assert invalid_top_k.status_code == 422


def test_storage_contention_error_is_safe_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = create_app(make_settings(tmp_path))
    with TestClient(application) as client:
        monkeypatch.setattr(
            application.state.memory_service.repository,
            "search",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                sqlite3.OperationalError("database is locked: secret path")
            ),
        )
        response = client.post(
            "/v1/memory/search", json=search_payload(query="anything")
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"reason": "storage_temporarily_unavailable"}
    }
    assert "secret path" not in response.text


def test_concurrent_official_shape_preserves_idempotency_and_isolation(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    application = create_app(settings)
    user_count = 64

    with TestClient(application) as client:
        payloads = [
            add_payload(
                user_id=f"eval:load:user-{index}",
                request_id=f"eval:load:add-{index}",
                content=f"Private marker-{index} belongs only to user-{index}.",
            )
            for index in range(user_count)
        ]
        with ThreadPoolExecutor(max_workers=64) as executor:
            add_responses = list(
                executor.map(
                    lambda payload: client.post("/v1/memory/add", json=payload),
                    payloads,
                )
            )
        assert all(response.status_code == 200 for response in add_responses)

        replay_payload = add_payload(
            user_id="eval:load:user-0",
            request_id="eval:load:add-0",
            content="Private marker-0 belongs only to user-0.",
        )
        with ThreadPoolExecutor(max_workers=32) as executor:
            replay_responses = list(
                executor.map(
                    lambda _index: client.post(
                        "/v1/memory/add", json=replay_payload
                    ),
                    range(32),
                )
            )
        assert all(response.status_code == 200 for response in replay_responses)

        searches = [
            search_payload(
                user_id=f"eval:load:user-{index % user_count}",
                query=f"marker-{index % user_count}",
                top_k=100,
            )
            for index in range(128)
        ]
        with ThreadPoolExecutor(max_workers=128) as executor:
            search_responses = list(
                executor.map(
                    lambda payload: client.post(
                        "/v1/memory/search", json=payload
                    ),
                    searches,
                )
            )

    assert all(response.status_code == 200 for response in search_responses)
    for index, response in enumerate(search_responses):
        data = response.json()["data"]
        expected_user = index % user_count
        assert 0 < len(data) <= 100
        assert all(f"user-{expected_user}" in item["content"] for item in data)
    with sqlite3.connect(settings.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM add_requests").fetchone()[0] == 64
        assert connection.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0] == 64


def test_equal_score_events_use_stable_source_order_across_databases(
    tmp_path: Path,
) -> None:
    payload = {
        "request_id": "eval:stable:add-1",
        "messages": [
            {"role": "user", "content": f"Shared topic detail {index}"}
            for index in range(5)
        ],
        "user_id": "eval:stable:user-1",
        "session_id": "eval:stable:session-1",
    }
    ranked_ids: list[list[str]] = []
    for database_name in ("first.db", "second.db"):
        settings = make_settings(
            tmp_path,
            db_path=tmp_path / database_name,
            markdown_view_dir=None,
        )
        with TestClient(create_app(settings)) as client:
            assert client.post("/v1/memory/add", json=payload).status_code == 200
            response = client.post(
                "/v1/memory/search",
                json={
                    "query": "Shared topic",
                    "options": None,
                    "user_id": "eval:stable:user-1",
                    "top_k": 5,
                },
            )
        assert response.status_code == 200
        ranked_ids.append([item["id"] for item in response.json()["data"]])

    expected = [
        stable_memory_id("eval:stable:user-1", "eval:stable:add-1", ordinal)
        for ordinal in reversed(range(5))
    ]
    assert ranked_ids == [expected, expected]
