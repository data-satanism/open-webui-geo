from pathlib import Path


def test_geotizer_download_proxy_exposes_all_companion_artifacts():
    source = (Path(__file__).parents[1] / 'open_webui' / 'routers' / 'geotizer.py').read_text(encoding='utf-8')
    for route in (
        '/files/{run_id}/geotizer.xlsx',
        '/files/{run_id}/source_report.md',
        '/files/{run_id}/source_report.pdf',
        '/files/{run_id}/state.json',
    ):
        assert f"@router.get('{route}')" in source


def test_geotizer_download_proxy_uses_persisted_tool_server_config():
    source = (Path(__file__).parents[1] / 'open_webui' / 'routers' / 'geotizer.py').read_text(encoding='utf-8')
    assert 'from open_webui.models.config import Config' in source
    assert "await Config.get('tool_server.connections', [])" in source
    assert "get('id') or '') == 'mcpgis'" in source
    assert 'request.app.state.config' not in source
