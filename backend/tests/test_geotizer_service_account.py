from open_webui.utils.geotizer_service_account import (
    DEFAULT_ALLOWED_ENDPOINTS,
    DEFAULT_BASE_MODEL_IDS,
    GeotizerServiceAccountSpec,
    add_group_read_grant,
    grant_tool_server_access,
    scoped_api_key_data,
    service_group_permissions,
)


def test_service_permissions_enable_only_required_elevations():
    permissions = service_group_permissions()

    assert permissions['features']['api_keys'] is True
    assert permissions['features']['web_search'] is True
    assert permissions['chat']['call'] is True
    assert permissions['workspace']['models'] is False
    assert permissions['workspace']['knowledge'] is False
    assert permissions['workspace']['tools'] is False
    assert permissions['features']['direct_tool_servers'] is False
    assert permissions['features']['code_interpreter'] is False


def test_scoped_key_contains_only_geo_teaser_endpoints():
    data = scoped_api_key_data(GeotizerServiceAccountSpec())

    assert data == {
        'purpose': 'geotizer_orchestrator',
        'allowed_endpoints': list(DEFAULT_ALLOWED_ENDPOINTS),
    }


def test_the_key_cannot_open_a_sub_chat():
    """CORE-BOUNDARY-01: `/api/v1/chats/new` was scoped in for the HTTP
    sub-chat delegator, which Multitask Orchestration v3 replaced with an
    in-process loop.

    The test above cannot catch this, and it is worth saying why rather than
    leaving two tests that look alike: it compares `scoped_api_key_data`'s
    output against `DEFAULT_ALLOWED_ENDPOINTS`, so it holds the plumbing between
    the two and nothing about their contents. Adding an endpoint back would keep
    it green. This one names the route.
    """
    endpoints = scoped_api_key_data(GeotizerServiceAccountSpec())['allowed_endpoints']

    assert '/api/v1/chats/new' not in endpoints
    # Stated positively so the pair does not both pass by the scope emptying out.
    assert '/api/chat/completions' in endpoints
    assert '/api/v1/knowledge' in endpoints


def test_service_account_includes_only_required_base_model_chain():
    spec = GeotizerServiceAccountSpec()

    assert spec.base_model_ids == DEFAULT_BASE_MODEL_IDS
    assert spec.base_model_ids == ('TESTAGENT.Qwen/Qwen3.5-35B-A3B-GPTQ-Int4',)


def test_group_read_grant_is_idempotent_and_preserves_other_grants():
    existing = [
        {
            'principal_type': 'user',
            'principal_id': 'owner',
            'permission': 'write',
        }
    ]

    once = add_group_read_grant(existing, 'service-group')
    twice = add_group_read_grant(once, 'service-group')

    assert existing == [
        {
            'principal_type': 'user',
            'principal_id': 'owner',
            'permission': 'write',
        }
    ]
    assert once == twice
    assert len(twice) == 2


def test_tool_server_grant_changes_only_selected_connection():
    connections = [
        {
            'info': {'id': 'mcpgis'},
            'config': {'access_grants': []},
        },
        {
            'info': {'id': 'unrelated'},
            'config': {'access_grants': []},
        },
    ]

    updated, found = grant_tool_server_access(
        connections,
        group_id='service-group',
        server_ids=('mcpgis',),
    )

    assert found == ('mcpgis',)
    assert connections[0]['config']['access_grants'] == []
    assert updated[0]['config']['access_grants'] == [
        {
            'principal_type': 'group',
            'principal_id': 'service-group',
            'permission': 'read',
        }
    ]
    assert updated[1] == connections[1]
