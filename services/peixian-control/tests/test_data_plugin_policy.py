from control.data_plugin_policy import ACTIVE_KINDS, ACTIVE_PLUGIN_IDS, ACTIVE_VERSION, installable, valid_bundle
from shared.theft_provider_v2 import CATALOG


def test_exactly_eight_active_provider_plugins():
    assert len(ACTIVE_KINDS) == len(ACTIVE_PLUGIN_IDS) == 8
    assert set(ACTIVE_KINDS) <= set(CATALOG)
    assert "peixian-theft-warnings" not in ACTIVE_PLUGIN_IDS
    assert all(installable(pid) for pid in ACTIVE_PLUGIN_IDS)
    assert not any(installable(pid) for pid in (
        "sample-records", "peixian-synthetic-records", "peixian-records-night",
        "peixian-theft-warnings", "peixian-mobility-records",
    ))


def test_bundle_must_register_only_matching_tool():
    for kind in ACTIVE_KINDS:
        pid = "peixian-theft-" + kind.replace("_", "-")
        own = "peixian_query_" + kind
        assert valid_bundle({"id": pid, "version": ACTIVE_VERSION, "tools": [own]})
        assert not valid_bundle({"id": pid, "version": "2.0.0", "tools": [own]})
        assert not valid_bundle({"id": pid, "version": ACTIVE_VERSION, "tools": [own, "other"]})
        assert not valid_bundle({"id": pid, "version": ACTIVE_VERSION, "tools": ["peixian_query_profile"] if kind != "profile" else ["peixian_query_night"]})
    assert not valid_bundle({"id": "peixian-theft-warnings", "tools": ["peixian_query_warnings"]})
