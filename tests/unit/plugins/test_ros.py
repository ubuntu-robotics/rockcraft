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
"""Tests for the colcon plugin runtime-dependency staging callback."""

import pathlib
import subprocess
from unittest import mock

import pytest
from craft_parts import Part, PartInfo, ProjectDirs, ProjectInfo, Step, StepInfo
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


def test_parse_rosdep_resolve_dependencies_ignores_blank_lines():
    parsed = _ros._parse_rosdep_resolve_dependencies("dep", "\n#apt\n\nlibfoo\n\n")

    assert parsed == {"apt": {"libfoo"}}


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


def test_resolve_apt_dependencies_runs_rosdep_with_the_build_environment(monkeypatch):
    workspace_pkg = _make_pkg("my_pkg", [_make_dep("rclcpp")])
    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": workspace_pkg} if "src" in path else {},
    )
    run_result = mock.Mock()
    run_result.stdout = b"#apt\nros-humble-rclcpp"
    run = mock.Mock(return_value=run_result)
    monkeypatch.setattr(_ros.subprocess, "run", run)
    environment = {"ROS_HOME": "/custom/ros-home", "ROS_PYTHON_VERSION": "3"}

    _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
        environment=environment,
    )

    assert run.call_args.kwargs["env"] == environment


def test_resolve_apt_dependencies_resolves_all_dependencies_in_one_call(monkeypatch):
    # Dependencies shared by several packages are resolved once, and all the
    # unique keys go in a single rosdep call (sorted, for a stable command).
    pkg_a = _make_pkg("pkg_a", [_make_dep("rclcpp"), _make_dep("std_msgs")])
    pkg_b = _make_pkg("pkg_b", [_make_dep("std_msgs"), _make_dep("rclcpp")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"pkg_a": pkg_a, "pkg_b": pkg_b} if "src" in path else {},
    )

    run_result = mock.Mock()
    run_result.stdout = (
        b"#ROSDEP[rclcpp]\n#apt\nros-humble-rclcpp\n"
        b"#ROSDEP[std_msgs]\n#apt\nros-humble-std-msgs\n"
    )
    run = mock.Mock(return_value=run_result)
    monkeypatch.setattr(_ros.subprocess, "run", run)

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == {"ros-humble-rclcpp", "ros-humble-std-msgs"}
    run.assert_called_once()
    assert run.call_args.args[0] == [
        "rosdep",
        "resolve",
        "rclcpp",
        "std_msgs",
        "--rosdistro",
        "humble",
    ]


def test_resolve_apt_dependencies_no_dependencies_no_rosdep_call(monkeypatch):
    pkg = _make_pkg("my_pkg", [])
    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": pkg} if "src" in path else {},
    )
    run = mock.Mock()
    monkeypatch.setattr(_ros.subprocess, "run", run)

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == set()
    run.assert_not_called()


def test_resolve_apt_dependencies_batch_failure_names_failed_keys(monkeypatch):
    pkg = _make_pkg("my_pkg", [_make_dep("rclcpp"), _make_dep("not_a_key")])
    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": pkg} if "src" in path else {},
    )
    # rosdep reports the keys it could resolve; the failed one has no section
    # content.
    error = subprocess.CalledProcessError(
        1,
        ["rosdep"],
        output=b"#ROSDEP[not_a_key]\n#ROSDEP[rclcpp]\n#apt\nros-humble-rclcpp\n",
        stderr=b"ERROR: no rosdep rule for 'not_a_key'",
    )
    monkeypatch.setattr(_ros.subprocess, "run", mock.Mock(side_effect=error))

    with pytest.raises(_ros.RosdepError) as raised:
        _ros._resolve_apt_dependencies(
            part_src="/part/src",
            part_install="/part/install",
            ros_version="2",
            ros_distro="humble",
        )

    assert "['not_a_key']" in str(raised.value)
    assert "rclcpp" not in str(raised.value)
    assert raised.value.details is not None
    assert "no rosdep rule for 'not_a_key'" in raised.value.details


@pytest.mark.parametrize(
    ("names", "output", "expected"),
    [
        pytest.param(
            ["a", "b"],
            "#ROSDEP[a]\n#apt\npkg-a\n#ROSDEP[b]\n#apt\npkg-b\n#pip\npip-b",
            {"a": {"apt": {"pkg-a"}}, "b": {"apt": {"pkg-b"}, "pip": {"pip-b"}}},
            id="several-keys",
        ),
        pytest.param(
            ["a", "b"],
            "#ROSDEP[a]\n#ROSDEP[b]\n#apt\npkg-b",
            {"a": {}, "b": {"apt": {"pkg-b"}}},
            id="unresolved-key-has-an-empty-section",
        ),
        pytest.param(
            ["a"],
            "#apt\npkg-a",
            {"a": {"apt": {"pkg-a"}}},
            id="single-key-has-no-header",
        ),
        pytest.param(["a", "b"], "", {}, id="empty-output"),
    ],
)
def test_parse_rosdep_resolve_batch(names, output, expected):
    assert _ros._parse_rosdep_resolve_batch(names, output) == expected


def test_parse_rosdep_resolve_batch_unexpected_result():
    # Without headers, the output cannot be attributed to a key.
    with pytest.raises(_ros.RosdepUnexpectedResultError):
        _ros._parse_rosdep_resolve_batch(["a", "b"], "#apt\npkg")


def test_resolve_apt_dependencies_warns_on_non_apt_dependencies(monkeypatch, caplog):
    workspace_pkg = _make_pkg("my_pkg", [_make_dep("python-dep")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": workspace_pkg} if "src" in path else {},
    )

    run_result = mock.Mock()
    run_result.stdout = b"#apt\nlibfoo\n#pip\npython-dep"
    monkeypatch.setattr(_ros.subprocess, "run", mock.Mock(return_value=run_result))

    packages = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    assert packages == {"libfoo"}
    assert "Unhandled non-apt dependencies" in caplog.text


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
    assert raised.value.details is not None
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
    seen = {}

    def fake_fetch(**kwargs):
        seen["fetch_dir"] = kwargs["stage_packages_path"]
        seen["fetch_dir_existed"] = kwargs["stage_packages_path"].is_dir()
        return ["ros-humble-rclcpp", "libfoo"]

    def fake_unpack(**kwargs):
        seen["unpack_debs"] = kwargs["stage_packages_path"]
        seen["unpack_dir"] = kwargs["install_path"]
        seen["unpack_dir_existed"] = kwargs["install_path"].is_dir()
        # Unpacking (and the normalization it does) happens in the scratch
        # directory: the install directory is untouched at this point.
        seen["install_untouched"] = not (install_path / "new.txt").exists()
        (kwargs["install_path"] / "new.txt").write_text("from the runtime deb")
        (kwargs["install_path"] / "existing.txt").write_text("from the runtime deb")

    fetch = mock.Mock(side_effect=fake_fetch)
    unpack = mock.Mock(side_effect=fake_unpack)
    monkeypatch.setattr(_ros.Repository, "configure", configure)
    monkeypatch.setattr(_ros.Repository, "fetch_stage_packages", fetch)
    monkeypatch.setattr(_ros.Repository, "unpack_stage_packages", unpack)

    install_path = tmp_path / "install"
    install_path.mkdir()
    (install_path / "existing.txt").write_text("from the build")
    # Packages that the part's own stage-packages already unpacked.
    pull_owned_debs = tmp_path / "stage_packages"
    pull_owned_debs.mkdir()
    for deb in ("libfoo_1%3a2.0-1_amd64.deb", "ros-humble-std-msgs_5.3.5-1_amd64.deb"):
        (pull_owned_debs / deb).touch()

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
    # What is already unpacked is not fetched again.
    assert kwargs["packages_filters"] == {"libfoo", "ros-humble-std-msgs"}
    unpack.assert_called_once_with(
        stage_packages_path=seen["fetch_dir"], install_path=seen["unpack_dir"]
    )
    # The packages go through scratch directories next to the install dir, not
    # through the part's own (pull-owned) stage_packages directory...
    assert seen["fetch_dir"].parent == tmp_path
    assert seen["fetch_dir"] != tmp_path / "stage_packages"
    assert seen["fetch_dir_existed"]
    assert seen["unpack_dir"].parent == tmp_path
    assert seen["unpack_dir"] != install_path
    assert seen["unpack_dir_existed"]
    assert seen["install_untouched"]
    # ...and they are gone afterwards, so nothing stale outlives the hook.
    assert not seen["fetch_dir"].exists()
    assert not seen["unpack_dir"].exists()
    # The unpacked files are merged without overwriting what the build made.
    assert (install_path / "new.txt").read_text() == "from the runtime deb"
    assert (install_path / "existing.txt").read_text() == "from the build"


def test_stage_runtime_dependencies_cleans_up_on_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _ros, "_resolve_apt_dependencies", mock.Mock(return_value={"libfoo"})
    )
    monkeypatch.setattr(_ros.Repository, "configure", mock.Mock())
    seen = {}

    def fake_fetch(**kwargs):
        seen["dir"] = kwargs["stage_packages_path"]
        raise RuntimeError("download failed")

    monkeypatch.setattr(
        _ros.Repository, "fetch_stage_packages", mock.Mock(side_effect=fake_fetch)
    )
    install_path = tmp_path / "install"
    install_path.mkdir()

    with pytest.raises(RuntimeError, match="download failed"):
        _ros.stage_runtime_dependencies(
            part_src=str(tmp_path / "src"),
            part_install=str(install_path),
            ros_version="2",
            ros_distro="humble",
            target_arch="amd64",
            stage_cache_dir=str(tmp_path / "cache"),
            base="ubuntu@22.04",
        )

    assert not seen["dir"].exists()
    assert not list(tmp_path.glob("*ros-runtime-*"))


def test_merge_without_overwriting_keeps_existing_entries(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "a" / "deep").mkdir(parents=True)
    (destination / "a").mkdir(parents=True)
    (destination / "a").chmod(0o750)

    (source / "a" / "existing.txt").write_text("new")
    (source / "a" / "new.txt").write_text("new")
    (source / "a" / "deep" / "nested.txt").write_text("new")
    (source / "link").symlink_to("a/new.txt")
    (source / "existing-link").symlink_to("a/new.txt")
    (destination / "a" / "existing.txt").write_text("original")
    (destination / "existing-link").symlink_to("original-target")

    _ros._merge_without_overwriting(source, destination)

    # What is already there is kept, even a symlink to nothing...
    assert (destination / "a" / "existing.txt").read_text() == "original"
    assert (destination / "existing-link").readlink() == pathlib.Path("original-target")
    # ...the rest is merged in...
    assert (destination / "a" / "new.txt").read_text() == "new"
    assert (destination / "a" / "deep" / "nested.txt").read_text() == "new"
    assert (destination / "link").readlink() == pathlib.Path("a/new.txt")
    # ...and the existing directories keep their metadata.
    assert (destination / "a").stat().st_mode & 0o777 == 0o750


def test_merge_without_overwriting_through_directory_symlinks(tmp_path):
    # e.g. the lib -> usr/lib symlink of a usrmerged install directory.
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "lib").mkdir(parents=True)
    (source / "lib" / "libfoo.so").write_text("lib")
    (destination / "usr" / "lib").mkdir(parents=True)
    (destination / "lib").symlink_to("usr/lib")

    _ros._merge_without_overwriting(source, destination)

    assert (destination / "usr" / "lib" / "libfoo.so").read_text() == "lib"
    assert (destination / "lib").is_symlink()


def test_get_unpacked_stage_packages(tmp_path):
    install_path = tmp_path / "install"
    stage_packages = tmp_path / "stage_packages"
    stage_packages.mkdir()
    for name in (
        "libc6_2.40-1ubuntu1_amd64.deb",
        "libfoo_1%3a2.0-1_amd64.deb",
        "ros-humble-rclcpp_16.0.1-1_amd64.deb",
        "not-a-package.txt",
    ):
        (stage_packages / name).touch()

    assert _ros._get_unpacked_stage_packages(install_path) == {
        "libc6",
        "libfoo",
        "ros-humble-rclcpp",
    }


def test_get_unpacked_stage_packages_without_stage_packages(tmp_path):
    # Parts without stage-packages have no (pull-owned) stage_packages dir.
    assert _ros._get_unpacked_stage_packages(tmp_path / "install") == set()


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


def _make_step_info(tmp_path, environment=None) -> StepInfo:
    """Create a build StepInfo for a colcon part, with the given step environment.

    The step environment is written to the part's ``run/environment.sh``,
    mimicking what craft-parts generates for the build script.
    """
    dirs = ProjectDirs(work_dir=tmp_path)
    project_info = ProjectInfo(
        project_dirs=dirs,
        application_name="test",
        project_name="test-rock",
        cache_dir=tmp_path / "cache",
        base="ubuntu@22.04",
        arch="amd64",
    )
    part = Part("my-part", {"source": ".", "plugin": "colcon"}, project_dirs=dirs)
    step_info = StepInfo(
        part_info=PartInfo(project_info=project_info, part=part), step=Step.BUILD
    )

    if environment is not None:
        run_dir = part.part_run_dir
        run_dir.mkdir(parents=True)
        (run_dir / "environment.sh").write_text(
            "# Environment\n"
            + "".join(f'export {key}="{value}"\n' for key, value in environment.items())
        )

    return step_info


def test_callback_stages_runtime_dependencies(monkeypatch, tmp_path):
    staging = mock.Mock()
    fix = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", fix)
    step_info = _make_step_info(
        tmp_path, environment={"ROS_DISTRO": "humble", "ROS_VERSION": "2"}
    )

    result = _ros.stage_runtime_dependencies_callback(step_info)

    assert result is True
    staging.assert_called_once_with(
        part_src=str(tmp_path / "parts/my-part/src"),
        part_install=str(tmp_path / "parts/my-part/install"),
        ros_version="2",
        ros_distro="humble",
        target_arch="amd64",
        stage_cache_dir=str((tmp_path / "cache").resolve()),
        base="ubuntu@22.04",
        colcon_packages=None,
        colcon_packages_ignore=None,
        environment=mock.ANY,
    )
    # The BLAS/LAPACK symlink fix runs after the staging.
    fix.assert_called_once_with(part_install=str(tmp_path / "parts/my-part/install"))


def test_callback_evaluates_references_in_the_environment(monkeypatch, tmp_path):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", mock.Mock())
    step_info = _make_step_info(
        tmp_path,
        environment={"CHOSEN_DISTRO": "humble", "ROS_DISTRO": "${CHOSEN_DISTRO}"},
    )

    _ros.stage_runtime_dependencies_callback(step_info)

    assert staging.call_args.kwargs["ros_distro"] == "humble"


def test_callback_passes_the_build_environment_to_staging(monkeypatch, tmp_path):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", mock.Mock())
    step_info = _make_step_info(
        tmp_path,
        environment={"ROS_DISTRO": "humble", "ROS_HOME": "/custom/ros-home"},
    )

    _ros.stage_runtime_dependencies_callback(step_info)

    environment = staging.call_args.kwargs["environment"]
    assert environment["ROS_HOME"] == "/custom/ros-home"
    assert environment["ROS_DISTRO"] == "humble"


def test_callback_packages_filter_and_default_ros_version(monkeypatch, tmp_path):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", mock.Mock())
    # ROS_VERSION is not set: the callback defaults to ROS 2.
    step_info = _make_step_info(tmp_path, environment={"ROS_DISTRO": "jazzy"})

    _ros.stage_runtime_dependencies_callback(
        step_info, colcon_packages=["demo_nodes_cpp"]
    )

    assert staging.call_args.kwargs["colcon_packages"] == ["demo_nodes_cpp"]


def test_callback_forwards_colcon_packages_ignore(monkeypatch, tmp_path):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", mock.Mock())
    step_info = _make_step_info(tmp_path, environment={"ROS_DISTRO": "jazzy"})

    _ros.stage_runtime_dependencies_callback(
        step_info, colcon_packages_ignore=["unused_pkg"]
    )

    assert staging.call_args.kwargs["colcon_packages_ignore"] == ["unused_pkg"]
    assert staging.call_args.kwargs["ros_version"] == "2"
    assert staging.call_args.kwargs["ros_distro"] == "jazzy"


def test_callback_skips_when_ros_distro_unset(monkeypatch, tmp_path, caplog):
    staging = mock.Mock()
    fix = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    monkeypatch.setattr(_ros, "_fix_library_alternatives", fix)
    step_info = _make_step_info(tmp_path, environment={"ROS_VERSION": "2"})

    with caplog.at_level("WARNING"):
        result = _ros.stage_runtime_dependencies_callback(step_info)

    assert result is True
    staging.assert_not_called()
    fix.assert_not_called()
    assert "ROS_DISTRO is not set" in caplog.text


def test_callback_skips_when_no_environment_file(monkeypatch, tmp_path, caplog):
    staging = mock.Mock()
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", staging)
    # No environment.sh written for the part.
    step_info = _make_step_info(tmp_path)

    with caplog.at_level("WARNING"):
        result = _ros.stage_runtime_dependencies_callback(step_info)

    assert result is True
    staging.assert_not_called()
    assert "ROS_DISTRO is not set" in caplog.text


def test_callback_propagates_errors(monkeypatch, tmp_path):
    # Errors raised by the staging propagate so that the build fails with a
    # clean message (RockcraftError carries details/resolution).
    error = _ros.RosdepError(
        message="Failed to resolve the runtime dependency 'rclcpp'.",
        details="rosdep stderr: boom",
        resolution="Add the matching ros2-* extension.",
    )
    monkeypatch.setattr(
        _ros, "stage_runtime_dependencies", mock.Mock(side_effect=error)
    )
    step_info = _make_step_info(tmp_path, environment={"ROS_DISTRO": "humble"})

    with pytest.raises(_ros.RosdepError, match="Failed to resolve"):
        _ros.stage_runtime_dependencies_callback(step_info)


def test_callback_restores_blas_lapack_symlinks(monkeypatch, tmp_path):
    # The callback recreates the BLAS/LAPACK SONAME symlinks after staging
    # (staging unpacks packages without running maintainer scripts).
    monkeypatch.setattr(_ros, "stage_runtime_dependencies", mock.Mock())
    install_dir = tmp_path / "parts/my-part/install"
    provider_dir = install_dir / "usr/lib/x86_64-linux-gnu/blas"
    provider_dir.mkdir(parents=True)
    (provider_dir / "libblas.so.3").touch()
    step_info = _make_step_info(tmp_path, environment={"ROS_DISTRO": "humble"})

    _ros.stage_runtime_dependencies_callback(step_info)

    soname_link = install_dir / "usr/lib/x86_64-linux-gnu/libblas.so.3"
    assert soname_link.is_symlink()
    assert soname_link.readlink() == pathlib.Path("blas/libblas.so.3")


def test_fix_library_alternatives_keeps_existing_files(tmp_path):
    install_dir = tmp_path / "install"
    provider_dir = install_dir / "usr/lib/x86_64-linux-gnu/lapack"
    provider_dir.mkdir(parents=True)
    (provider_dir / "liblapack.so.3").touch()
    existing = install_dir / "usr/lib/x86_64-linux-gnu/liblapack.so.3"
    existing.touch()

    _ros._fix_library_alternatives(part_install=str(install_dir))

    # An existing canonical file/symlink is left untouched.
    assert not existing.is_symlink()


def test_fix_library_alternatives_replaces_dangling_symlink(tmp_path):
    install_dir = tmp_path / "install"
    lib_dir = install_dir / "usr/lib/x86_64-linux-gnu"
    provider_dir = lib_dir / "blas"
    provider_dir.mkdir(parents=True)
    (provider_dir / "libblas.so.3").touch()
    # e.g. an alternatives link whose target only exists on a real system.
    (lib_dir / "libblas.so.3").symlink_to("/etc/alternatives/libblas.so.3")

    _ros._fix_library_alternatives(part_install=str(install_dir))

    assert (lib_dir / "libblas.so.3").readlink() == pathlib.Path("blas/libblas.so.3")
    assert (lib_dir / "libblas.so.3").exists()


def test_fix_library_alternatives_no_libraries(tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    # Nothing staged: no-op, no error.
    _ros._fix_library_alternatives(part_install=str(install_dir))

    assert list(install_dir.iterdir()) == []


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
        colcon_packages=["selected_pkg"],
    )

    assert result == {"ros-humble-rclcpp"}
    # Only one rosdep resolve call for rclcpp (selected_pkg's dep).
    # libfoo (other_pkg's dep) must NOT be resolved.
    assert run_mock.call_count == 1
    cmd_args = run_mock.call_args[0][0]
    assert "rclcpp" in cmd_args


def test_resolve_apt_dependencies_skips_colcon_packages_ignore(monkeypatch):
    # The dependencies of packages listed in 'colcon_packages_ignore' (which
    # colcon
    # does not build) are neither resolved nor staged.
    built_pkg = _make_pkg("built_pkg", [_make_dep("rclcpp")])
    ignored_pkg = _make_pkg("ignored_pkg", [_make_dep("libfoo")])

    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: (
            {"built_pkg": built_pkg, "ignored_pkg": ignored_pkg}
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
        colcon_packages_ignore=["ignored_pkg"],
    )

    assert result == {"ros-humble-rclcpp"}
    run_mock.assert_called_once()
    assert "libfoo" not in run_mock.call_args[0][0]
    ignored_pkg.evaluate_conditions.assert_not_called()


def test_resolve_apt_dependencies_ignore_wins_over_selection(monkeypatch):
    # A package that is both selected and ignored is not built by colcon.
    pkg = _make_pkg("my_pkg", [_make_dep("rclcpp")])
    monkeypatch.setattr(
        _ros.catkin_packages,
        "find_packages",
        lambda path: {"my_pkg": pkg} if "src" in path else {},
    )
    run_mock = mock.Mock()
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    result = _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
        colcon_packages=["my_pkg"],
        colcon_packages_ignore=["my_pkg"],
    )

    assert result == set()
    run_mock.assert_not_called()


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
    run_result.stdout = b"#ROSDEP[libfoo]\n#apt\nsome-pkg\n#ROSDEP[rclcpp]\n#apt\nother"
    run_mock = mock.Mock(return_value=run_result)
    monkeypatch.setattr(_ros.subprocess, "run", run_mock)

    _ros._resolve_apt_dependencies(
        part_src="/part/src",
        part_install="/part/install",
        ros_version="2",
        ros_distro="humble",
    )

    # Both packages processed: their dependencies share one rosdep call.
    run_mock.assert_called_once()
    cmd_args = run_mock.call_args[0][0]
    assert "rclcpp" in cmd_args
    assert "libfoo" in cmd_args
