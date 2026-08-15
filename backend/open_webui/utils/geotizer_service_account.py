"""Idempotent least-privilege provisioning for the GeoTeaser orchestrator."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

DEFAULT_SERVICE_EMAIL = 'geotizer-orchestrator@service.local'
DEFAULT_SERVICE_NAME = 'GeoTeaser Orchestrator'
DEFAULT_SERVICE_GROUP_NAME = 'GeoTeaser Orchestrator Service'
DEFAULT_SOURCE_KNOWLEDGE_GROUP_NAME = 'Test Team'
# GEOMAS-DEF-001. The three ids here named models that exist in no contour, so
# the service group was granted access to nothing and every specialist call
# raised `Model not found`. The confirmed inventory is `orchestration-agent`,
# `web-agent`, `kb-agent`, `gisagent`, `skilledagent-final`
# (`GMM/prompt-verification.md` 14.1). `test_geotizer_model_identities.py` holds
# every default in this repository to that inventory.
DEFAULT_AGENT_MODEL_IDS = (
    'gisagent',
    'kb-agent',
    'web-agent',
)
DEFAULT_BASE_MODEL_IDS = ('TESTAGENT.Qwen/Qwen3.5-35B-A3B-GPTQ-Int4',)
DEFAULT_TOOL_SERVER_IDS = ('mcpgis',)
# CORE-BOUNDARY-01. Every chat route is gone. They existed so the HTTP sub-chat
# delegator could open one chat per specialist, poll it and delete it, and
# Multitask Orchestration v3 replaced that transport with an in-process agent
# loop -- its own header says "No httpx, no /api/v1/chats/new, no polling, no
# citation walk over fetched chat objects", which is all three routes.
#
# The first attempt removed only `/api/v1/chats/new` and left the two
# `{chat_id}` entries, on the reasoning that the review named one entry and a
# contour check was not available. That was wrong, and not conservatively wrong:
# `{name}` in a per-key pattern compiles to `[^/]+`, so
# `/api/v1/chats/{chat_id}` is `^/api/v1/chats/[^/]+$` and matches
# `/api/v1/chats/new` exactly. Deleting the literal revoked nothing at all,
# while the code comment, `docs/geotizer-service-account.md` and a new test all
# said the key could no longer open a chat. A wrong security claim is worse than
# the privilege it describes, because it is the one nobody re-checks.
#
# `test_the_key_cannot_reach_any_chat_route` now asks `is_api_key_path_allowed`
# rather than reading this tuple, which is the only question that has an answer,
# and `test_the_documented_scope_is_the_scope_that_is_provisioned` holds
# `docs/geotizer-service-account.md` to this constant -- the page was left
# listing two revoked routes for exactly as long as it took a review to notice.
DEFAULT_ALLOWED_ENDPOINTS = (
    '/api/chat/completions',
    '/api/v1/knowledge',
)


@dataclass(frozen=True)
class GeotizerServiceAccountSpec:
    email: str = DEFAULT_SERVICE_EMAIL
    name: str = DEFAULT_SERVICE_NAME
    group_name: str = DEFAULT_SERVICE_GROUP_NAME
    source_knowledge_group_name: str = DEFAULT_SOURCE_KNOWLEDGE_GROUP_NAME
    agent_model_ids: tuple[str, ...] = DEFAULT_AGENT_MODEL_IDS
    base_model_ids: tuple[str, ...] = DEFAULT_BASE_MODEL_IDS
    tool_server_ids: tuple[str, ...] = DEFAULT_TOOL_SERVER_IDS
    allowed_endpoints: tuple[str, ...] = DEFAULT_ALLOWED_ENDPOINTS
    rotate_key: bool = False


def service_group_permissions() -> dict[str, Any]:
    """Only privileges that exceed the normal read-only API surface."""
    return {
        'workspace': {
            'models': False,
            'knowledge': False,
            'prompts': False,
            'tools': False,
        },
        'sharing': {
            'models': False,
            'knowledge': False,
            'prompts': False,
            'tools': False,
        },
        'chat': {
            'call': True,
        },
        'features': {
            'api_keys': True,
            'web_search': True,
            'direct_tool_servers': False,
            'code_interpreter': False,
            'image_generation': False,
        },
        'settings': {
            'interface': False,
        },
    }


def scoped_api_key_data(spec: GeotizerServiceAccountSpec) -> dict[str, Any]:
    return {
        'purpose': 'geotizer_orchestrator',
        'allowed_endpoints': list(spec.allowed_endpoints),
    }


def add_group_read_grant(
    access_grants: list[dict[str, Any]] | None,
    group_id: str,
) -> list[dict[str, Any]]:
    grants = deepcopy(access_grants or [])
    expected = {
        'principal_type': 'group',
        'principal_id': group_id,
        'permission': 'read',
    }
    if not any(
        isinstance(grant, dict) and all(grant.get(key) == value for key, value in expected.items()) for grant in grants
    ):
        grants.append(expected)
    return grants


def grant_tool_server_access(
    connections: list[dict[str, Any]],
    *,
    group_id: str,
    server_ids: tuple[str, ...],
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    updated = deepcopy(connections)
    found: set[str] = set()
    for connection in updated:
        if not isinstance(connection, dict):
            continue
        info = connection.get('info')
        server_id = str(info.get('id') or '') if isinstance(info, dict) else ''
        if server_id not in server_ids:
            continue
        config = connection.setdefault('config', {})
        if not isinstance(config, dict):
            config = {}
            connection['config'] = config
        config['access_grants'] = add_group_read_grant(
            config.get('access_grants'),
            group_id,
        )
        found.add(server_id)
    return updated, tuple(sorted(found))


async def _ensure_service_group(
    spec: GeotizerServiceAccountSpec,
    *,
    owner_id: str,
):
    from open_webui.models.groups import (
        GroupForm,
        Groups,
        GroupUpdateForm,
    )

    group = await Groups.get_group_by_name(spec.group_name)
    permissions = service_group_permissions()
    if group is None:
        group = await Groups.insert_new_group(
            owner_id,
            GroupForm(
                name=spec.group_name,
                description=(
                    'Non-interactive GeoTeaser orchestration identity. '
                    'API scope and resource grants are managed by provisioning.'
                ),
                permissions=permissions,
            ),
        )
    else:
        group = await Groups.update_group_by_id(
            group.id,
            GroupUpdateForm(
                name=spec.group_name,
                description=group.description,
                permissions=permissions,
                data=group.data,
            ),
        )
    if group is None:
        raise RuntimeError('Failed to create or update the service group.')
    return group


async def _ensure_service_user(spec: GeotizerServiceAccountSpec):
    from open_webui.models.users import Users

    user = await Users.get_user_by_email(spec.email)
    if user is None:
        user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'open-webui:{spec.email}'))
        user = await Users.insert_new_user(
            user_id,
            spec.name,
            spec.email,
            role='user',
        )
    if user is None:
        raise RuntimeError('Failed to create the service user.')
    if user.role != 'user':
        raise RuntimeError(f'Service identity must have role=user, got {user.role!r}.')
    return user


async def _grant_knowledge_from_group(
    *,
    source_group_id: str,
    service_group_id: str,
) -> tuple[str, ...]:
    from open_webui.models.access_grants import AccessGrants
    from open_webui.models.knowledge import Knowledges

    granted: list[str] = []
    for knowledge in await Knowledges.get_knowledge_bases():
        grants = await AccessGrants.get_grants_by_resource(
            'knowledge',
            knowledge.id,
        )
        source_can_read = any(
            grant.principal_type == 'group' and grant.principal_id == source_group_id and grant.permission == 'read'
            for grant in grants
        )
        if not source_can_read:
            continue
        await AccessGrants.grant_access(
            'knowledge',
            knowledge.id,
            'group',
            service_group_id,
            'read',
        )
        granted.append(knowledge.id)
    return tuple(sorted(granted))


async def _grant_model_access(
    *,
    model_ids: tuple[str, ...],
    service_group_id: str,
) -> None:
    from open_webui.models.access_grants import AccessGrants
    from open_webui.models.models import Models

    missing_models = [model_id for model_id in model_ids if await Models.get_model_by_id(model_id) is None]
    if missing_models:
        raise RuntimeError(f'Required models are missing: {missing_models}')
    for model_id in model_ids:
        await AccessGrants.grant_access(
            'model',
            model_id,
            'group',
            service_group_id,
            'read',
        )


async def _grant_tool_server_access(
    *,
    server_ids: tuple[str, ...],
    service_group_id: str,
) -> tuple[str, ...]:
    from open_webui.models.config import Config

    connections = await Config.get('tool_server.connections', []) or []
    updated_connections, found_server_ids = grant_tool_server_access(
        connections,
        group_id=service_group_id,
        server_ids=server_ids,
    )
    missing_servers = sorted(set(server_ids) - set(found_server_ids))
    if missing_servers:
        raise RuntimeError(f'Required tool servers are missing: {missing_servers}')
    if updated_connections != connections:
        await Config.upsert({'tool_server.connections': updated_connections})
    return found_server_ids


async def provision_geotizer_service_account(
    spec: GeotizerServiceAccountSpec,
) -> dict[str, Any]:
    from open_webui.models.groups import Groups
    from open_webui.models.users import Users
    from open_webui.utils.auth import create_api_key

    owner = await Users.get_super_admin_user()
    if owner is None:
        raise RuntimeError('An admin user is required to own the service group.')

    source_group = await Groups.get_group_by_name(spec.source_knowledge_group_name)
    if source_group is None:
        raise RuntimeError(f'Source knowledge group is missing: {spec.source_knowledge_group_name!r}.')

    service_user = await _ensure_service_user(spec)
    service_group = await _ensure_service_group(spec, owner_id=owner.id)

    current_groups = await Groups.get_groups_by_member_id(service_user.id)
    if service_group.id not in {group.id for group in current_groups}:
        updated_group = await Groups.add_users_to_group(
            service_group.id,
            [service_user.id],
        )
        if updated_group is None:
            raise RuntimeError('Failed to add the service user to its group.')

    await _grant_model_access(
        model_ids=spec.agent_model_ids + spec.base_model_ids,
        service_group_id=service_group.id,
    )

    knowledge_ids = await _grant_knowledge_from_group(
        source_group_id=source_group.id,
        service_group_id=service_group.id,
    )
    if not knowledge_ids:
        raise RuntimeError('The source group does not have read access to any knowledge base.')

    found_server_ids = await _grant_tool_server_access(
        server_ids=spec.tool_server_ids,
        service_group_id=service_group.id,
    )

    existing_key = await Users.get_user_api_key_by_id(service_user.id)
    api_key = create_api_key() if spec.rotate_key or not existing_key else existing_key
    await Users.update_user_api_key_by_id(
        service_user.id,
        api_key,
        data=scoped_api_key_data(spec),
    )

    # CORE-BOUNDARY-01: the write of `valves['api_key']` into
    # `mainagent_tool_yulong` is deleted rather than ported. That tool and that
    # valve no longer exist, and specialists now run as the requesting user, so
    # the write had nowhere to land -- and what it landed was a live credential
    # in a DB-stored Workspace Tool's valves, readable by anyone who can open
    # the tool. The key stays on the service user, where the ACL applies.

    return {
        'service_user_id': service_user.id,
        'service_email': service_user.email,
        'service_role': service_user.role,
        'interactive_auth_created': False,
        'service_group_id': service_group.id,
        'service_group_name': service_group.name,
        'agent_model_ids': list(spec.agent_model_ids),
        'base_model_ids': list(spec.base_model_ids),
        'knowledge_base_count': len(knowledge_ids),
        'tool_server_ids': list(found_server_ids),
        'allowed_endpoints': list(spec.allowed_endpoints),
        'api_key_rotated': bool(spec.rotate_key or not existing_key),
        'api_key_fingerprint': hashlib.sha256(api_key.encode()).hexdigest()[:12],
    }


def result_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
