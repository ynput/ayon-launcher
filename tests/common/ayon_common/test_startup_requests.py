"""Server requests made on startup by connection and distribution logic.

No AYON server is needed, requests are replaced with fakes.
"""
import json
import os
import platform
import sys

import pytest

# 'ayon_common' is imported as top level package, same as in 'start.py'
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        ),
        "common",
    ),
)

from ayon_common.connection import credentials  # noqa: E402
from ayon_common.distribution import control  # noqa: E402

PLATFORM_NAME = platform.system().lower()
PACKAGE_FILENAME = "ayon_2601010000_test.zip"


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"Status {self.status_code}")


class FakeConnection:
    def __init__(self, valid_token=True, username="artist"):
        self.has_valid_token = valid_token
        self.username = username
        self.requested = []

    def get(self, endpoint):
        self.requested.append(endpoint)
        return FakeResponse({"name": self.username})


@pytest.fixture
def server_url(monkeypatch):
    monkeypatch.setenv("AYON_SERVER_URL", "http://localhost:5000")


def test_connect_without_url_does_not_connect(monkeypatch):
    monkeypatch.delenv("AYON_SERVER_URL", raising=False)
    monkeypatch.setattr(
        credentials, "create_global_connection", pytest.fail
    )
    assert credentials.connect_and_check_login() == (True, True)


def test_connect_to_unreachable_server(monkeypatch, server_url):
    def create_global_connection():
        raise ConnectionError("Server is down")

    monkeypatch.setattr(
        credentials, "create_global_connection", create_global_connection
    )
    assert credentials.connect_and_check_login() == (True, True)


@pytest.mark.parametrize(
    "valid_token, username, expected, requested",
    [
        (True, None, (False, False), []),
        (False, None, (False, True), []),
        (True, "artist", (False, False), ["users/me"]),
        (True, "other", (False, True), ["users/me"]),
    ],
)
def test_connect_validates_once(
    monkeypatch, server_url, valid_token, username, expected, requested
):
    created = []

    def create_global_connection():
        con = FakeConnection(valid_token=valid_token)
        created.append(con)
        return con

    monkeypatch.setattr(
        credentials, "create_global_connection", create_global_connection
    )
    assert credentials.connect_and_check_login(username) == expected
    assert len(created) == 1
    assert created[0].requested == requested


def _bundle(name, **kwargs):
    data = {
        "name": name,
        "isProduction": False,
        "isStaging": False,
        "isDev": False,
        "activeUser": None,
        "installerVersion": None,
        "addons": {},
        "dependencyPackages": {PLATFORM_NAME: PACKAGE_FILENAME},
    }
    data.update(kwargs)
    return data


@pytest.fixture
def distribution_env(monkeypatch):
    for key in (
        "AYON_STUDIO_BUNDLE_NAME",
        "AYON_BUNDLE_NAME",
        "AYON_PROJECT_NAME",
        "AYON_USE_DEV",
        "AYON_USE_STAGING",
    ):
        monkeypatch.delenv(key, raising=False)


def _create_distribution(tmp_path, use_dev=False):
    return control.AYONDistribution(
        addon_dirpath=str(tmp_path / "addons"),
        dependency_dirpath=str(tmp_path / "dependency_packages"),
        bundles_info=[
            _bundle("production", isProduction=True),
            _bundle("dev", isDev=True, activeUser="artist"),
        ],
        use_dev=use_dev,
        use_staging=False,
        skip_installer_dist=True,
    )


def _store_progress(dirpath, state="done"):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, "dist_progress.json"), "w") as stream:
        json.dump(
            {
                "state": state,
                "progress_id": "test",
                "checksum": "abc",
                "checksum_algorithm": "sha256",
            },
            stream,
        )


def _fail_request(*args, **kwargs):
    pytest.fail("Unexpected server request")


@pytest.mark.parametrize(
    "dirname", [PACKAGE_FILENAME, os.path.splitext(PACKAGE_FILENAME)[0]]
)
def test_distributed_dependency_package_skips_server(
    monkeypatch, tmp_path, distribution_env, dirname
):
    monkeypatch.setattr(control.ayon_api, "get", _fail_request)
    monkeypatch.setattr(
        control.ayon_api, "get_dependency_packages", _fail_request
    )
    package_dir = tmp_path / "dependency_packages" / dirname
    _store_progress(str(package_dir))

    dist_item = _create_distribution(tmp_path).get_dependency_dist_item()
    assert dist_item.state == control.UpdateState.UPDATED
    assert not dist_item.need_distribution
    assert dist_item.target_dirpath == str(package_dir)


@pytest.mark.parametrize("state", [None, "moving", "failed"])
def test_missing_dependency_package_requests_server(
    monkeypatch, tmp_path, distribution_env, state
):
    requested = []

    def get_dependency_packages():
        requested.append(True)
        return {"packages": [{
            "filename": PACKAGE_FILENAME,
            "platform": PLATFORM_NAME,
            "checksum": "abc",
            "checksumAlgorithm": "sha256",
            "sources": [{"type": "server"}],
            "sourceAddons": {},
            "pythonModules": {},
        }]}

    monkeypatch.setattr(
        control.ayon_api, "get_dependency_packages", get_dependency_packages
    )
    if state is not None:
        _store_progress(
            str(tmp_path / "dependency_packages" / PACKAGE_FILENAME), state
        )

    dist_item = _create_distribution(tmp_path).get_dependency_dist_item()
    assert requested == [True]
    assert dist_item.need_distribution
    assert dist_item.sources


def test_production_does_not_request_user(
    monkeypatch, tmp_path, distribution_env
):
    monkeypatch.setattr(control.ayon_api, "get", _fail_request)
    monkeypatch.setattr(control.ayon_api, "get_user", _fail_request)

    distribution = _create_distribution(tmp_path)
    assert distribution.studio_bundle_to_use.name == "production"


def test_dev_bundle_requests_only_user_name(
    monkeypatch, tmp_path, distribution_env
):
    requested = []

    def get(endpoint):
        requested.append(endpoint)
        return FakeResponse({"name": "artist"})

    monkeypatch.setattr(control.ayon_api, "get", get)
    monkeypatch.setattr(control.ayon_api, "get_user", _fail_request)

    distribution = _create_distribution(tmp_path, use_dev=True)
    assert distribution.studio_bundle_to_use.name == "dev"
    assert requested == ["users/me"]
