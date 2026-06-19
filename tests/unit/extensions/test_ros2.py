# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2026 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for the ROS 2 extensions (ros2-humble, ros2-jazzy, ros2-lyrical)."""

import pytest
from rockcraft import extensions
from rockcraft.errors import ExtensionError
from rockcraft.extensions.ros2 import (
    _ROS2_APT_KEY_ID,
    _ROS2_APT_URL,
    ROS2HumbleExtension,
    ROS2JazzyExtension,
    ROS2LyricalExtension,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PART_SNIPPET = {
    "plugin": "colcon",
    "source": ".",
    "build-packages": ["ros-{distro}-rclcpp"],
}


def _make_input_yaml(
    base: str, extension_name: str, *, extra_parts: bool = False
) -> dict:
    yaml: dict = {
        "name": "my-ros2-rock",
        "base": base,
        "platforms": {"amd64": {}},
        "extensions": [extension_name],
        "parts": {
            "my-node": {
                "plugin": "colcon",
                "source": ".",
            }
        },
    }
    if extra_parts:
        yaml["parts"]["another-part"] = {"plugin": "nil"}
    return yaml


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ros2_extensions(mock_extensions, monkeypatch):
    monkeypatch.setenv("ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS", "1")
    extensions.register("ros2-humble", ROS2HumbleExtension)
    extensions.register("ros2-jazzy", ROS2JazzyExtension)
    extensions.register("ros2-lyrical", ROS2LyricalExtension)


# ---------------------------------------------------------------------------
# Static property tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ext_class", "expected_distro", "expected_suite", "expected_bases"),
    [
        (
            ROS2HumbleExtension,
            "humble",
            "jammy",
            ("ubuntu@22.04", "ubuntu:22.04"),
        ),
        (
            ROS2JazzyExtension,
            "jazzy",
            "noble",
            ("ubuntu@24.04", "ubuntu:24.04"),
        ),
        (
            ROS2LyricalExtension,
            "lyrical",
            "resolute",
            ("ubuntu@26.04", "ubuntu:26.04"),
        ),
    ],
)
def test_ros2_extension_properties(
    tmp_path,
    ext_class,
    expected_distro,
    expected_suite,
    expected_bases,
):
    ext = ext_class(project_root=tmp_path, yaml_data={})
    assert ext.distro == expected_distro
    assert ext.suite == expected_suite
    assert ext.get_supported_bases() == expected_bases
    assert ext.is_experimental(None) is True
    assert ext.is_experimental(expected_bases[0]) is True


# ---------------------------------------------------------------------------
# Snippet tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ext_class", "distro", "suite"),
    [
        (ROS2HumbleExtension, "humble", "jammy"),
        (ROS2JazzyExtension, "jazzy", "noble"),
        (ROS2LyricalExtension, "lyrical", "resolute"),
    ],
)
def test_ros2_get_root_snippet(tmp_path, ext_class, distro, suite):
    ext = ext_class(project_root=tmp_path, yaml_data={})
    assert ext.get_root_snippet() == {
        "package-repositories": [
            {
                "type": "apt",
                "url": _ROS2_APT_URL,
                "components": ["main"],
                "suites": [suite],
                "key-id": _ROS2_APT_KEY_ID,
            }
        ],
    }


@pytest.mark.parametrize(
    ("ext_class", "distro"),
    [
        (ROS2HumbleExtension, "humble"),
        (ROS2JazzyExtension, "jazzy"),
        (ROS2LyricalExtension, "lyrical"),
    ],
)
def test_ros2_get_root_snippet_emits_launcher_notice(
    tmp_path, emitter, ext_class, distro
):
    # The implicit ros2-launch runtime contract must be surfaced to the user.
    ext = ext_class(project_root=tmp_path, yaml_data={})

    ext.get_root_snippet()

    emitter.assert_progress(
        f"ros2-{distro}: run ROS 2 service and entrypoint commands "
        "through the 'ros2-launch' wrapper so the ROS 2 environment is "
        'sourced at runtime, e.g. "command: ros2-launch ros2 run '
        '<package> <node>".',
        permanent=True,
    )


@pytest.mark.parametrize(
    ("ext_class", "distro"),
    [
        (ROS2HumbleExtension, "humble"),
        (ROS2JazzyExtension, "jazzy"),
        (ROS2LyricalExtension, "lyrical"),
    ],
)
def test_ros2_get_part_snippet(tmp_path, ext_class, distro):
    ext = ext_class(project_root=tmp_path, yaml_data={})
    assert ext.get_part_snippet() == {
        "build-environment": [{"ROS_DISTRO": distro}],
    }


@pytest.mark.parametrize(
    ("ext_class", "distro"),
    [
        (ROS2HumbleExtension, "humble"),
        (ROS2JazzyExtension, "jazzy"),
        (ROS2LyricalExtension, "lyrical"),
    ],
)
def test_ros2_get_parts_snippet_launcher(tmp_path, ext_class, distro):
    ext = ext_class(project_root=tmp_path, yaml_data={})

    parts = ext.get_parts_snippet()

    part_name = f"ros2-{distro}-launch"
    assert part_name in parts
    part = parts[part_name]
    assert part["plugin"] == "dump"
    assert part["organize"] == {"ros2-launch": "usr/bin/ros2-launch"}
    assert part["stage"] == ["usr/bin/ros2-launch"]
    # The source must point to the extensions data directory for ros2.
    assert part["source"].endswith("/extensions/ros2")


# ---------------------------------------------------------------------------
# Full apply_extensions integration tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("ros2_extensions")
@pytest.mark.parametrize(
    ("extension_name", "base", "distro", "suite"),
    [
        ("ros2-humble", "ubuntu@22.04", "humble", "jammy"),
        ("ros2-jazzy", "ubuntu@24.04", "jazzy", "noble"),
        ("ros2-lyrical", "ubuntu@26.04", "lyrical", "resolute"),
    ],
)
def test_ros2_apply_extension(tmp_path, extension_name, base, distro, suite):
    yaml_data = _make_input_yaml(base, extension_name)
    applied = extensions.apply_extensions(tmp_path, yaml_data)

    assert "extensions" not in applied
    assert applied["package-repositories"] == [
        {
            "type": "apt",
            "url": _ROS2_APT_URL,
            "components": ["main"],
            "suites": [suite],
            "key-id": _ROS2_APT_KEY_ID,
        }
    ]
    assert applied["parts"]["my-node"]["build-environment"] == [{"ROS_DISTRO": distro}]


@pytest.mark.usefixtures("ros2_extensions")
def test_ros2_build_environment_prepended_to_existing(tmp_path):
    """Extension build-environment is prepended before any user-supplied entries."""
    yaml_data = _make_input_yaml("ubuntu@24.04", "ros2-jazzy")
    yaml_data["parts"]["my-node"]["build-environment"] = [{"MY_VAR": "1"}]
    applied = extensions.apply_extensions(tmp_path, yaml_data)

    assert applied["parts"]["my-node"]["build-environment"] == [
        {"ROS_DISTRO": "jazzy"},
        {"MY_VAR": "1"},
    ]


@pytest.mark.usefixtures("ros2_extensions")
def test_ros2_build_environment_injected_into_all_parts(tmp_path):
    """ROS_DISTRO is injected into every part, not just the first one."""
    yaml_data = _make_input_yaml("ubuntu@24.04", "ros2-jazzy", extra_parts=True)
    applied = extensions.apply_extensions(tmp_path, yaml_data)

    # The extension also injects its own launcher part which has no
    # build-environment — skip it and check only the user-provided parts.
    user_parts = {
        name: part
        for name, part in applied["parts"].items()
        if not name.startswith("ros2-")
    }
    for part in user_parts.values():
        assert {"ROS_DISTRO": "jazzy"} in part["build-environment"]


@pytest.mark.usefixtures("ros2_extensions")
def test_ros2_existing_package_repositories_preserved(tmp_path):
    """A user-supplied package-repositories list is merged, not replaced."""
    yaml_data = _make_input_yaml("ubuntu@22.04", "ros2-humble")
    yaml_data["package-repositories"] = [{"type": "apt", "ppa": "myteam/myproject"}]
    applied = extensions.apply_extensions(tmp_path, yaml_data)

    repos = applied["package-repositories"]
    assert len(repos) == 2
    # Extension repo is prepended
    assert repos[0]["suites"] == ["jammy"]
    assert repos[1]["ppa"] == "myteam/myproject"


# ---------------------------------------------------------------------------
# Validation error tests
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("ros2_extensions")
@pytest.mark.parametrize(
    ("extension_name", "wrong_base"),
    [
        ("ros2-humble", "ubuntu@24.04"),
        ("ros2-jazzy", "ubuntu@22.04"),
        ("ros2-lyrical", "ubuntu@24.04"),
    ],
)
def test_ros2_wrong_base_raises(tmp_path, extension_name, wrong_base):
    yaml_data = _make_input_yaml(wrong_base, extension_name)
    with pytest.raises(ExtensionError, match="does not support base"):
        extensions.apply_extensions(tmp_path, yaml_data)
