from pathlib import Path

import pytest
from open_webui.utils.geotizer_download import (
    GeotizerDownloadConfigError,
    resolve_geotizer_download_target,
)


def test_geotizer_download_proxy_exposes_all_companion_artifacts():
    source = (Path(__file__).parents[1] / 'open_webui' / 'routers' / 'geotizer.py').read_text(encoding='utf-8')
    for route in (
        '/files/{run_id}/geotizer.xlsx',
        '/files/{run_id}/source_report.md',
        '/files/{run_id}/source_report.pdf',
        '/files/{run_id}/state.json',
    ):
        assert f"@router.get('{route}')" in source


def test_download_target_uses_configured_connection_url():
    target = resolve_geotizer_download_target(
        servers=[
            {
                'id': 'mcpgis',
                'idx': 0,
                'url': 'http://stale-gis:10002',
            }
        ],
        connections=[
            {
                'url': 'http://gis-mcp:10002/',
                'auth_type': 'session',
            }
        ],
        run_id='588e28df-b912-4d61-abae-36a0fc0887a1',
        artifact='geotizer.xlsx',
        allowed_artifacts=frozenset({'geotizer.xlsx'}),
    )

    assert target.url == ('http://gis-mcp:10002/geotizer/files/' '588e28df-b912-4d61-abae-36a0fc0887a1/geotizer.xlsx')
    assert target.connection == {
        'url': 'http://gis-mcp:10002/',
        'auth_type': 'session',
    }


def test_download_target_recovers_from_stale_cache_index_by_server_id():
    expected_connection = {
        'info': {'id': 'mcpgis'},
        'url': 'http://gis-mcp:10002',
        'auth_type': 'none',
    }

    target = resolve_geotizer_download_target(
        servers=[
            {
                'id': 'server:mcpgis',
                'idx': 0,
                'url': 'http://stale-gis:10002',
            }
        ],
        connections=[
            {'info': {'id': 'other'}, 'url': 'http://other:9000'},
            expected_connection,
        ],
        run_id='588e28df-b912-4d61-abae-36a0fc0887a1',
        artifact='source_report.pdf',
        allowed_artifacts=frozenset({'source_report.pdf'}),
    )

    assert target.connection is expected_connection
    assert target.url.endswith('/geotizer/files/' '588e28df-b912-4d61-abae-36a0fc0887a1/source_report.pdf')


def test_download_target_falls_back_to_cached_server_url_without_credentials():
    target = resolve_geotizer_download_target(
        servers=[
            {
                'id': 'mcp:mcpgis',
                'idx': 'stale',
                'url': 'http://gis-mcp:10002',
            }
        ],
        connections=[],
        run_id='588e28df-b912-4d61-abae-36a0fc0887a1',
        artifact='state.json',
        allowed_artifacts=frozenset({'state.json'}),
    )

    assert target.connection is None
    assert target.url == ('http://gis-mcp:10002/geotizer/files/' '588e28df-b912-4d61-abae-36a0fc0887a1/state.json')


@pytest.mark.parametrize(
    ('run_id', 'artifact'),
    [
        ('../state', 'geotizer.xlsx'),
        ('588e28df-b912-4d61-abae-36a0fc0887a1', '../state.json'),
    ],
)
def test_download_target_rejects_unbounded_paths(run_id, artifact):
    with pytest.raises(GeotizerDownloadConfigError):
        resolve_geotizer_download_target(
            servers=[{'id': 'mcpgis', 'url': 'http://gis-mcp:10002'}],
            connections=[],
            run_id=run_id,
            artifact=artifact,
            allowed_artifacts=frozenset({'geotizer.xlsx'}),
        )
