# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright 2026 Canonical Ltd.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.
"""Tests for the colcon plugin runtime-dependency staging helper."""

import subprocess
from unittest import mock

import pytest
from rockcraft.plugins import _ros


def test_parse_rosdep_resolve_dependencies_apt_and_pip():
    output = "#apt\npackage1\npackage2\n#pip\npip-package1"

    parsed = _ros._parse_rosdep_resolve_dependencies("dep", output)

    assert parsed == {
        "apt": {"package1", "package2"},
        "pip": {"pip-package1"},
    }


def test_parse_rosdep_resolve_dependencies_apt_only():
    parsed = _ros._parse_rosdep_resolve_dependencies("dep", "#apt\nlibfoo")

    assert parsed == {"apt": {"libfoo"}}


def test_parse_rosdep_resolve_dependencies_spaced_header_and_inline_packages():
    # The installer header may carry a space after the ``#`` and a single line
    # may list several whitespace-separated packages.
    output = "# apt\npackage1 package2\n# pip\npip-package1"

    parsed = _ros._parse_rosdep_resolve_dependencies("dep", output)

    assert parsed == {
        "apt": {"package1", "package2"},
        "pip": {"pip-package1"},
    }


def test_parse_rosdep_resolve_dependencies_unexpected_result():
    # Output that lists a package before any installer header is unexpected.
    with pytest.raises(_ros.RosdepUnexpectedResultError) as raised:
        _ros._parse_rosdep_resolve_dependencies("dep", "package-without-header")

    assert "dep" in str(raised.value)


def _make_pkg(name, exec_depends):
    pkg = mock.Mock()
    pkg.name = name
    pkg.exec_depends = exec_depends
    return pkg


def _make_dep(name, *, evaluated_condition=True):
    dep = mock.Mock()
    dep.name = name
    dep.evaluated_condition = evaluated_condition
    return dep


def test_resolve_apt_dependencies_resolves_exec_depends(monkeypatch):
    workspace_pkg = _make_pkg("my_pkg", [_make_dep("rclcpp")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": workspace_pkg} if "src" in path else {},
    )

    run_result = mock.Mock()
    run_result.stdout = b"#apt\nros-humble-rclcpp"
    monkeypatch.setattr(_ros.subprocess, "run", mock.Mock(return_value=run_result))

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == {"ros-humble-rclcpp"}
    workspace_pkg.evaluate_conditions.assert_called_once_with(
        {"ROS_VERSION": "2", "ROS_DISTRO": "humble", "ROS_PYTHON_VERSION": "3"}
    )


def test_resolve_apt_dependencies_skips_false_conditions(monkeypatch):
    workspace_pkg = _make_pkg(
        "my_pkg", [_make_dep("rclcpp", evaluated_condition=False)]
    )

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": workspace_pkg} if "src" in path else {},
    )
    run_mock = mock.Mock()
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == set()
    run_mock.assert_not_called()


def test_resolve_apt_dependencies_skips_local_packages(monkeypatch):
    workspace_pkg = _make_pkg("my_pkg", [_make_dep("sibling_pkg")])
    installed_pkg = _make_pkg("sibling_pkg", [])

    def fake_find_packages(path):
        if "src" in path:
            return {"my_pkg": workspace_pkg}
        return {"sibling_pkg": installed_pkg}

    monkeypatch.setattr(_ros.catkin_packages, "find_packages", fake_find_packages)
    run_mock = mock.Mock()
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == set()
    run_mock.assert_not_called()


def test_resolve_apt_dependencies_rosdep_failure(monkeypatch):
    workspace_pkg = _make_pkg("my_pkg", [_make_dep("rclcpp")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": workspace_pkg} if "src" in path else {},
    )

    error = subprocess.CalledProcessError(1, ["rosdep"], output=b"out", stderr=b"err")
    monkeypatch.setattr(_ros.subprocess, "run", mock.Mock(side_effect=error))

    with pytest.raises(_ros.RosdepError) as raised:
        _ros._resolve_apt_dependencies(
            part_src="/part/src",
            part_install="/part/install",
            ros_version="2",
            ros_distro="humble",
        )

    # The error names the dependency and distro, surfaces the rosdep output as
    # details, and offers an actionable resolution.
    assert "rclcpp" in str(raised.value)
    assert "humble" in str(raised.value)
    assert "err" in raised.value.details
    assert raised.value.resolution is not None
    assert "ros2-* extension" in raised.value.resolution


def test_stage_runtime_dependencies_fetches_and_unpacks(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _ros,
        "_resolve_apt_dependencies",
        mock.Mock(return_value={"ros-humble-rclcpp", "libfoo"}),
    )
    configure = mock.Mock()
    fetch = mock.Mock(return_value=["ros-humble-rclcpp", "libfoo"])
    unpack = mock.Mock()
    monkeypatch.setattr(_ros.Repository, "configure", configure)
    monkeypatch.setattr(_ros.Repository, "fetch_stage_packages", fetch)
    monkeypatch.setattr(_ros.Repository, "unpack_stage_packages", unpack)

    install_path = tmp_path / "install"

    _ros.stage_runtime_dependencies(
        part_src=str(tmp_path / "src"),
        part_install=str(install_path),
        ros_version="2",
        ros_distro="humble",
        target_arch="amd64",
        stage_cache_dir=str(tmp_path / "cache"),
        base="ubuntu@22.04",
    )

    configure.assert_called_once_with("rockcraft")
    fetch.assert_called_once()
    _, kwargs = fetch.call_args
    # Packages are passed sorted.
    assert kwargs["package_names"] == ["libfoo", "ros-humble-rclcpp"]
    assert kwargs["arch"] == "amd64"
    assert kwargs["base"] == "ubuntu@22.04"
    assert kwargs["stage_packages_path"] == tmp_path / "stage_packages"
    unpack.assert_called_once_with(
        stage_packages_path=tmp_path / "stage_packages", install_path=install_path
    )


def test_stage_runtime_dependencies_no_packages(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _ros, "_resolve_apt_dependencies", mock.Mock(return_value=set())
    )
    fetch = mock.Mock()
    monkeypatch.setattr(_ros.Repository, "fetch_stage_packages", fetch)

    _ros.stage_runtime_dependencies(
        part_src=str(tmp_path / "src"),
        part_install=str(tmp_path / "install"),
        ros_version="2",
        ros_distro="humble",
        target_arch="amd64",
        stage_cache_dir=str(tmp_path / "cache"),
        base="ubuntu@22.04",
    )

    fetch.assert_not_called()


def test_main_invokes_staging(monkeypatch):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)

    exit_code = _ros.main(
        [
            "--part-src",
            "/part/src",
            "--part-install",
            "/part/install",
            "--ros-version",
            "2",
            "--ros-distro",
            "humble",
            "--target-arch",
            "amd64",
            "--stage-cache-dir",
            "/cache",
            "--base",
            "ubuntu@22.04",
        ]
    )

    assert exit_code == 0
    staging.assert_called_once_with(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
        target_arch="amd64",
        stage_cache_dir="/cache",
        base="ubuntu@22.04",
        packages=None,
    )


def test_main_invokes_staging_with_packages_filter(monkeypatch):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)

    exit_code = _ros.main(
        [
            "--part-src",
            "/part/src",
            "--part-install",
            "/part/install",
            "--ros-version",
            "2",
            "--ros-distro",
            "humble",
            "--target-arch",
            "amd64",
            "--stage-cache-dir",
            "/cache",
            "--base",
            "ubuntu@22.04",
            "--packages",
            "pkg_a",
            "pkg_b",
        ]
    )

    assert exit_code == 0
    staging.assert_called_once_with(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
        target_arch="amd64",
        stage_cache_dir="/cache",
        base="ubuntu@22.04",
        packages=["pkg_a", "pkg_b"],
    )


def test_main_surfaces_rockcraft_error_without_traceback(monkeypatch, caplog):
    # A RockcraftError from staging must be reported as a clean message with a
    # non-zero exit code, not propagated as a traceback.
    error = _ros.RosdepError(
        message="Failed to resolve the runtime dependency 'rclcpp'.",
        details="rosdep stderr: boom",
        resolution="Add the matching ros2-* extension.",
    )
    monkeypatch.setattr(
        _ros, "stage_runtime_dependencies", mock.Mock(side_effect=error)
    )

    with caplog.at_level("ERROR"):
        exit_code = _ros.main(
            [
                "--part-src",
                "/part/src",
                "--part-install",
                "/part/install",
                "--ros-version",
                "2",
                "--ros-distro",
                "humble",
                "--target-arch",
                "amd64",
                "--stage-cache-dir",
                "/cache",
                "--base",
                "ubuntu@22.04",
            ]
        )

    assert exit_code == 1
    log_text = caplog.text
    assert "Failed to resolve the runtime dependency 'rclcpp'." in log_text
    assert "rosdep stderr: boom" in log_text
    assert "Add the matching ros2-* extension." in log_text


def test_main_does_not_swallow_unexpected_errors(monkeypatch):
    # Genuinely unexpected (non-RockcraftError) failures must still propagate so
    # they are not silently turned into a clean exit.
    monkeypatch.setattr(
        _ros,
        "stage_runtime_dependencies",
        mock.Mock(side_effect=RuntimeError("unexpected")),
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        _ros.main(
            [
                "--part-src",
                "/part/src",
                "--part-install",
                "/part/install",
                "--ros-version",
                "2",
                "--ros-distro",
                "humble",
                "--target-arch",
                "amd64",
                "--stage-cache-dir",
                "/cache",
                "--base",
                "ubuntu@22.04",
            ]
        )


def test_resolve_apt_dependencies_respects_packages_filter(monkeypatch):
    # When 'packages' is given, only those packages' exec_depends are resolved.
    selected_pkg = _make_pkg("selected_pkg", [_make_dep("rclcpp")])
    other_pkg = _make_pkg("other_pkg", [_make_dep("libfoo")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: (
            {"selected_pkg": selected_pkg, "other_pkg": other_pkg}
            if "src" in path
            else {}
        ),
    )

    run_result = mock.Mock()
    run_result.stdout = b"#apt\nros-humble-rclcpp"
    run_mock = mock.Mock(return_value=run_result)
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    result = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
        packages=["selected_pkg"],
    )

    assert result == {"ros-humble-rclcpp"}
    # Only one rosdep resolve call for rclcpp (selected_pkg's dep).
    # libfoo (other_pkg's dep) must NOT be resolved.
    assert run_mock.call_count == 1
    cmd_args = run_mock.call_args[0][0]
    assert "rclcpp" in cmd_args


def test_resolve_apt_dependencies_no_filter_processes_all(monkeypatch):
    # When 'packages' is None, all packages in the source tree are processed.
    pkg_a = _make_pkg("pkg_a", [_make_dep("rclcpp")])
    pkg_b = _make_pkg("pkg_b", [_make_dep("libfoo")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"pkg_a": pkg_a, "pkg_b": pkg_b} if "src" in path else {},
    )

    run_result = mock.Mock()
    run_result.stdout = b"#apt\nsome-pkg"
    run_mock = mock.Mock(return_value=run_result)
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    # Both packages processed → two rosdep resolve calls.
    assert run_mock.call_count == 2
