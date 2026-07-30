from open_webui.utils.api_key_scope import (
    endpoint_matches_pattern,
    is_api_key_path_allowed,
    scoped_allowed_endpoints,
)


def test_key_without_scope_preserves_existing_global_policy():
    assert is_api_key_path_allowed('/api/v1/users', None)
    assert is_api_key_path_allowed('/api/v1/users', {})


def test_empty_or_malformed_scope_denies_every_endpoint():
    assert not is_api_key_path_allowed(
        '/api/chat/completions',
        {'allowed_endpoints': []},
    )
    assert not is_api_key_path_allowed(
        '/api/chat/completions',
        {'allowed_endpoints': '/api/chat/completions'},
    )


def test_scoped_key_allows_only_declared_exact_endpoint():
    data = {'allowed_endpoints': ['/api/chat/completions']}

    assert is_api_key_path_allowed('/api/chat/completions', data)
    assert is_api_key_path_allowed('/api/chat/completions/', data)
    assert not is_api_key_path_allowed('/api/chat/completions/debug', data)
    assert not is_api_key_path_allowed('/api/v1/users', data)


def test_route_parameter_matches_one_nonempty_path_segment():
    pattern = '/api/v1/chats/{chat_id}'

    assert endpoint_matches_pattern('/api/v1/chats/chat-123', pattern)
    assert not endpoint_matches_pattern('/api/v1/chats', pattern)
    assert not endpoint_matches_pattern('/api/v1/chats/chat-123/delete', pattern)


def test_delete_endpoint_requires_its_own_pattern():
    data = {
        'allowed_endpoints': [
            '/api/v1/chats/{chat_id}',
            '/api/v1/chats/{chat_id}/delete',
        ]
    }

    assert is_api_key_path_allowed('/api/v1/chats/chat-123', data)
    assert is_api_key_path_allowed('/api/v1/chats/chat-123/delete', data)
    assert not is_api_key_path_allowed('/api/v1/chats/chat-123/share', data)


def test_invalid_patterns_are_ignored():
    data = {
        'allowed_endpoints': [
            '/not-api',
            '/api/v1/chats/{bad-name}',
        ]
    }

    assert scoped_allowed_endpoints(data) == (
        '/not-api',
        '/api/v1/chats/{bad-name}',
    )
    assert not is_api_key_path_allowed('/api/v1/chats/123', data)
