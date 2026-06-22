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
# pylint: disable=protected-access

import typing
from pathlib import Path

import pytest
from craft_parts import Part, PartInfo, ProjectInfo
from rockcraft.models.project import Project
from rockcraft.plugins.colcon_plugin import ColconPlugin

from tests.util import ubuntu_only

pytestmark = ubuntu_only

# Extract the possible "base" values from the Literal annotation.
ALL_BASES = typing.get_args(typing.get_type_hints(Project)["base"])


def create_plugin(base: str, cache_dir: Path, **properties: object) -> ColconPlugin:
    part_info = PartInfo(
        project_info=ProjectInfo(
            application_name="test",
            project_name="test-rock",
            base=base,
            cache_dir=cache_dir,
        ),
        part=Part("my-part", {}),
    )
    plugin_properties = ColconPlugin.properties_class.unmarshal(
        {"source": ".", **properties}
    )
    return ColconPlugin(properties=plugin_properties, part_info=part_info)


def get_colcon_build_command(plugin: ColconPlugin) -> str:
    """Return the ``colcon build`` command from the plugin's build commands."""
    return next(line for line in plugin.get_build_commands() if "colcon build" in line)


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_packages(base, tmp_path):
    plugin = create_plugin(base, tmp_path)

    assert plugin.get_build_packages() == {
        "gcc",
        "g++",
        "cmake",
        "make",
        "colcon",
        "python3-colcon-core",
        "python3-colcon-cmake",
        "python3-colcon-package-selection",
        "python3-colcon-python-setup-py",
        "python3-colcon-parallel-executor",
        "python3-colcon-package-information",
        "python3-colcon-recursive-crawl",
        "python3-rosdep",
    }


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_environment(base, tmp_path):
    plugin = create_plugin(base, tmp_path)

    assert plugin.get_build_environment() == {
        "AMENT_PYTHON_EXECUTABLE": "/usr/bin/python3",
        "COLCON_PYTHON_EXECUTABLE": "/usr/bin/python3",
        "ROS_VERSION": "2",
        "ROS_PYTHON_VERSION": "3",
    }


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_default(base, tmp_path):
    plugin = create_plugin(base, tmp_path)

    build_command = get_colcon_build_command(plugin)

    assert "colcon build" in build_command
    assert "--merge-install" in build_command
    assert "--cmake-args -DCMAKE_BUILD_TYPE=Release" in build_command
    assert "--parallel-workers" in build_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_sources_workspace(base, tmp_path):
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    assert any("opt/ros/${ROS_DISTRO:-}/local_setup.sh" in line for line in commands)


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_sources_workspace_disables_nounset(base, tmp_path):
    # The ament setup scripts are not safe to source under ``set -u``, so the
    # plugin must disable ``nounset`` around the sourcing and restore it after.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    source_index = next(
        i
        for i, line in enumerate(commands)
        if "opt/ros/${ROS_DISTRO:-}/local_setup.sh" in line and line.startswith("AMENT")
    )
    assert commands[source_index - 1] == "set +u"
    assert commands[source_index + 1] == "set -u"


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_packages_select(base, tmp_path):
    plugin = create_plugin(base, tmp_path, **{"colcon-packages": ["demo_nodes_cpp"]})

    build_command = get_colcon_build_command(plugin)

    assert "--packages-select demo_nodes_cpp" in build_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_packages_ignore(base, tmp_path):
    plugin = create_plugin(base, tmp_path, **{"colcon-packages-ignore": ["unused_pkg"]})

    build_command = get_colcon_build_command(plugin)

    assert "--packages-ignore unused_pkg" in build_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_cmake_args(base, tmp_path):
    plugin = create_plugin(base, tmp_path, **{"colcon-cmake-args": ["-DFOO=bar"]})

    build_command = get_colcon_build_command(plugin)

    # The default Release build type is still injected alongside the user args.
    assert "--cmake-args -DCMAKE_BUILD_TYPE=Release -DFOO=bar" in build_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_cmake_args_build_type_override(base, tmp_path):
    plugin = create_plugin(
        base, tmp_path, **{"colcon-cmake-args": ["-DCMAKE_BUILD_TYPE=Debug"]}
    )

    build_command = get_colcon_build_command(plugin)

    # The user-provided build type takes precedence; Release is not injected.
    assert "-DCMAKE_BUILD_TYPE=Release" not in build_command
    assert "--cmake-args -DCMAKE_BUILD_TYPE=Debug" in build_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_runs_rosdep(base, tmp_path):
    # rosdep is used to install build dependencies before the colcon build runs.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    rosdep_init = next(i for i, line in enumerate(commands) if line == "rosdep init")
    rosdep_update = next(
        i for i, line in enumerate(commands) if line.startswith("rosdep update")
    )
    rosdep_install = next(
        i for i, line in enumerate(commands) if line.startswith("rosdep install")
    )
    colcon_build = next(i for i, line in enumerate(commands) if "colcon build" in line)

    # rosdep init -> update -> install all happen before the colcon build.
    assert rosdep_init < rosdep_update < rosdep_install < colcon_build


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_rosdep_update_runs_once(base, tmp_path):
    # rosdep update hits the network, so it must only run when the rosdep cache
    # has not been populated yet (it is shared across parts under $ROS_HOME).
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    rosdep_update = next(
        i for i, line in enumerate(commands) if line.startswith("rosdep update")
    )
    # The line immediately preceding `rosdep update` guards on an empty cache.
    guard = commands[rosdep_update - 1]
    assert guard.startswith("if [ -z ")
    assert "rosdep/sources.cache" in guard
    # The guard is closed with `fi` right after the update.
    assert commands[rosdep_update + 1] == "fi"


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_rosdep_guarded_on_ros_distro(base, tmp_path):
    # The whole rosdep block must be guarded on ROS_DISTRO being set.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    assert 'if [ -n "${ROS_DISTRO:-}" ]; then' in commands


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_rosdep_build_dependencies_only(base, tmp_path):
    # rosdep must only install build-time dependency types, leaving runtime
    # dependencies to be handled explicitly via stage-packages.
    plugin = create_plugin(base, tmp_path)

    rosdep_install = next(
        line
        for line in plugin.get_build_commands()
        if line.startswith("rosdep install")
    )

    assert "--dependency-types=buildtool" in rosdep_install
    assert "--dependency-types=build" in rosdep_install
    assert "--dependency-types=buildtool_export" in rosdep_install
    assert "--dependency-types=build_export" in rosdep_install
    # Runtime/test/doc dependency types are not installed at build time.
    assert "--dependency-types=exec" not in rosdep_install
    assert "--dependency-types=test" not in rosdep_install
    assert "--ignore-packages-from-source" in rosdep_install
    # The part's work source directory is referenced via the craft env var.
    assert '--from-paths "${CRAFT_PART_SRC_WORK}"' in rosdep_install


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_stages_runtime_dependencies(base, tmp_path):
    # Runtime dependencies are staged with rosdep after the colcon build.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    colcon_build = next(i for i, line in enumerate(commands) if "colcon build" in line)
    stage_command = next(
        i for i, line in enumerate(commands) if "rockcraft.plugins._ros" in line
    )

    # Runtime staging happens after the colcon build.
    assert colcon_build < stage_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_runtime_staging_guarded_on_ros_distro(base, tmp_path):
    # The runtime staging block must be guarded on ROS_DISTRO being set.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    stage_index = next(
        i for i, line in enumerate(commands) if "rockcraft.plugins._ros" in line
    )
    assert commands[stage_index - 1] == 'if [ -n "${ROS_DISTRO:-}" ]; then'
    # The staging command is followed by the BLAS/LAPACK symlink fix, then an
    # else branch warning, then `fi`.
    else_index = next(
        i
        for i, line in enumerate(commands[stage_index:], stage_index)
        if line == "else"
    )
    assert commands[else_index + 2] == "fi"


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_restores_blas_lapack_symlinks(base, tmp_path):
    # The runtime staging block recreates the BLAS/LAPACK SONAME symlinks that
    # update-alternatives would normally create, since staging packages does not
    # run maintainer scripts.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    stage_index = next(
        i for i, line in enumerate(commands) if "rockcraft.plugins._ros" in line
    )
    symlink_index = next(
        i for i, line in enumerate(commands) if "Restoring BLAS/LAPACK" in line
    )
    # The symlink fix runs after the runtime dependencies are staged.
    assert symlink_index > stage_index
    # The provider dirs (blas/, lapack/) are iterated and a relative SONAME
    # symlink is created in the parent (default linker) directory.
    assert "for _prov in blas lapack; do" in commands
    assert any(
        'ln -s "${_prov}/$(basename "${_so}")" "${_dest}"' in line for line in commands
    )


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_warns_when_ros_distro_unset(base, tmp_path):
    # When ROS_DISTRO is unset, both rosdep blocks must emit a visible warning
    # instead of silently skipping dependency resolution.
    plugin = create_plugin(base, tmp_path)

    commands = plugin.get_build_commands()

    warnings = [
        line
        for line in commands
        if "WARNING: ROS_DISTRO is not set" in line and line.startswith("echo ")
    ]
    # One warning for the build-dependency block, one for the runtime-staging
    # block.
    assert len(warnings) == 2
    assert any("build dependency installation" in line for line in warnings)
    assert any("runtime dependency staging" in line for line in warnings)
    # Each warning is written to stderr.
    assert all(line.rstrip().endswith(">&2") for line in warnings)


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_runtime_staging_invocation(base, tmp_path):
    # The runtime staging command invokes the helper module with the expected
    # craft environment variables.
    plugin = create_plugin(base, tmp_path)

    stage_command = next(
        line for line in plugin.get_build_commands() if "rockcraft.plugins._ros" in line
    )

    # The helper is invoked as a module with a clean environment.
    assert "env -i " in stage_command
    assert "-m rockcraft.plugins._ros" in stage_command
    assert '--part-src "${CRAFT_PART_SRC_WORK}"' in stage_command
    assert '--part-install "${CRAFT_PART_INSTALL}"' in stage_command
    assert '--ros-version "${ROS_VERSION}"' in stage_command
    assert '--ros-distro "${ROS_DISTRO}"' in stage_command
    assert '--target-arch "${CRAFT_TARGET_ARCH}"' in stage_command
    assert f"--base {base}" in stage_command
    # When no colcon-packages is set, --packages is not passed.
    assert "--packages" not in stage_command


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_rosdep_respects_colcon_packages(base, tmp_path):
    # When colcon-packages is set, rosdep install must scope its discovery to
    # those packages' directories rather than the whole source tree.
    plugin = create_plugin(base, tmp_path, **{"colcon-packages": ["demo_nodes_cpp"]})

    rosdep_install = next(
        line
        for line in plugin.get_build_commands()
        if line.startswith("rosdep install")
    )

    # The full source tree is NOT passed directly.
    assert '--from-paths "${CRAFT_PART_SRC_WORK}"' not in rosdep_install
    # colcon list (python3-colcon-package-information) is used to find only
    # the selected packages' directories.
    assert "--packages-select demo_nodes_cpp" in rosdep_install
    assert "--paths-only" in rosdep_install


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_rosdep_no_filter_without_colcon_packages(base, tmp_path):
    # When no colcon-packages is set, rosdep install processes the whole tree.
    plugin = create_plugin(base, tmp_path)

    rosdep_install = next(
        line
        for line in plugin.get_build_commands()
        if line.startswith("rosdep install")
    )

    assert '--from-paths "${CRAFT_PART_SRC_WORK}"' in rosdep_install
    assert "--packages-select" not in rosdep_install


@pytest.mark.parametrize("base", ALL_BASES)
def test_get_build_commands_runtime_staging_respects_colcon_packages(base, tmp_path):
    # When colcon-packages is set, the --packages flag is forwarded to the
    # _ros.py helper so that only the selected packages' runtime deps are staged.
    plugin = create_plugin(base, tmp_path, **{"colcon-packages": ["demo_nodes_cpp"]})

    stage_command = next(
        line for line in plugin.get_build_commands() if "rockcraft.plugins._ros" in line
    )

    assert "--packages demo_nodes_cpp" in stage_command
