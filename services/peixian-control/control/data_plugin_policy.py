"""New business-data publication policy; archived releases remain readable."""

from shared.theft_provider_v2 import CATALOG

ACTIVE_KINDS = (
    'incidents', 'captures', 'tracks', 'night', 'community',
    'warning_detail', 'warning_logs', 'profile',
)
ACTIVE_VERSION = '3.0.0'
ACTIVE_PLUGIN_IDS = frozenset('peixian-theft-' + kind.replace('_', '-') for kind in ACTIVE_KINDS)


def installable(plugin_id):
    return plugin_id in ACTIVE_PLUGIN_IDS


def valid_bundle(manifest):
    """An active release may expose exactly its own fixed query tool."""
    plugin_id = manifest.get('id')
    if not installable(plugin_id):
        return False
    kind = next(kind for kind in ACTIVE_KINDS if plugin_id == 'peixian-theft-' + kind.replace('_', '-'))
    return manifest.get('version') == ACTIVE_VERSION and manifest.get('tools') == ['peixian_query_' + kind] and kind in CATALOG
