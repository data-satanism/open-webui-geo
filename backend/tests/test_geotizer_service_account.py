import re
from pathlib import Path

import pytest

from open_webui.utils.api_key_scope import is_api_key_path_allowed
REPO_ROOT = Path(__file__).resolve().parents[2]

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


@pytest.mark.parametrize(
    'path',
    [
        '/api/v1/chats/new',
        '/api/v1/chats/abc-123',
        '/api/v1/chats/abc-123/delete',
        '/api/v1/chats/',
    ],
)
def test_the_key_cannot_reach_any_chat_route(path):
    """CORE-BOUNDARY-01: the chat routes belonged to the HTTP sub-chat
    delegator, which Multitask Orchestration v3 replaced with an in-process loop.

    Asked of `is_api_key_path_allowed`, not of the tuple, and that distinction
    is the whole finding. The first version of this test asserted
    `'/api/v1/chats/new' not in endpoints` and passed while the route was still
    reachable: `{chat_id}` compiles to `[^/]+`, so the retained
    `/api/v1/chats/{chat_id}` matched `/api/v1/chats/new`. A membership check
    over a list of patterns cannot answer a question about what those patterns
    match. Only the matcher can.
    """
    data = scoped_api_key_data(GeotizerServiceAccountSpec())

    assert is_api_key_path_allowed(path, data) is False


def test_the_documented_scope_is_the_scope_that_is_provisioned():
    """The operator-facing page is the only place the key's privileges are
    enumerated, and nothing checked it.

    It went stale in exactly the way that matters: the pass that removed the
    chat routes fixed the constant, the code comment and the tests, and left
    this page listing two revoked routes as callable *and* carrying the
    already-refuted argument for keeping them. The commit that did it names this
    file as one of the carriers of the wrong claim in its own message.
    """
    page = (REPO_ROOT / 'docs/geotizer-service-account.md').read_text(encoding='utf-8')
    listed = set(re.findall(r'^- `(/api/[^`]+)`[;.]$', page, re.M))

    assert listed == set(DEFAULT_ALLOWED_ENDPOINTS), (
        f'the page lists {sorted(listed)}; the provisioner grants '
        f'{sorted(DEFAULT_ALLOWED_ENDPOINTS)}'
    )


def test_the_key_can_still_reach_what_the_orchestrator_needs():
    """Stated positively so the pair does not both pass by the scope emptying
    out -- which, given the fix above deleted three entries, is a live risk."""
    data = scoped_api_key_data(GeotizerServiceAccountSpec())

    assert is_api_key_path_allowed('/api/chat/completions', data) is True
    assert is_api_key_path_allowed('/api/v1/knowledge', data) is True


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
