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

"""The Rockcraft colcon plugin."""

import logging
import os
import shlex
import sys

from craft_parts.plugins import colcon_plugin
from typing_extensions import override

logger = logging.getLogger(__name__)


class ColconPlugin(colcon_plugin.ColconPlugin):
    """A ColconPlugin plugin for Rockcraft.

    This plugin extends Craft-parts' vanilla colcon plugin to make it possible
    to build real ROS 2 (ament) workspaces inside a rock. Specifically:

    - Add the ``make`` and ``python3-colcon-recursive-crawl`` build packages,
      which are required to build ament_cmake packages (the former provides the
      CMake "Unix Makefiles" generator, the latter the ``--base-paths`` colcon
      discovery argument used by the plugin).
    - Use ``rosdep`` to automatically install the *build-time* dependencies
      declared in the workspace's ``package.xml`` files, so users do not have to
      list every ROS build dependency by hand in ``build-packages``.
    - Use ``rosdep`` to automatically stage the *runtime* dependencies declared
      in the workspace's ``package.xml`` files, so users do not have to list
      every ROS runtime dependency by hand in ``stage-packages``. The runtime
      dependencies are resolved to apt packages and unpacked into the part's
      install directory so they are primed into the rock.
    - Source the ROS environment with ``nounset`` (``set -u``) disabled. The
      ament setup scripts reference several unset shell variables, which would
      otherwise abort the ``set -euo pipefail`` build script.
    """

    @override
    def get_build_packages(self) -> set[str]:
        """Return a set of required packages to install in the build environment."""
        return super().get_build_packages() | {
            "make",
            "python3-colcon-recursive-crawl",
            "python3-rosdep",
        }

    @override
    def get_build_environment(self) -> dict[str, str]:
        """Return the environment to use in the build step.

        ``ROS_VERSION`` and ``ROS_PYTHON_VERSION`` are required to evaluate the
        conditional dependencies declared in the ``package.xml`` files when
        staging the runtime dependencies with rosdep.
        """
        return {
            **super().get_build_environment(),
            "ROS_VERSION": "2",
            "ROS_PYTHON_VERSION": "3",
        }

    @override
    def get_build_commands(self) -> list[str]:
        """Return a list of commands to run during the build step.

        The build-time dependencies declared in the workspace are installed with
        ``rosdep`` before the regular colcon build commands run, and the runtime
        dependencies are staged with ``rosdep`` afterwards.
        """
        return (
            self._get_rosdep_commands()
            + super().get_build_commands()
            + self._get_stage_runtime_dependencies_commands()
        )

    def _get_rosdep_commands(self) -> list[str]:
        """Return the commands that install build dependencies with rosdep.

        Only build-time dependency types are resolved here (``build``,
        ``buildtool`` and their ``_export`` counterparts); runtime dependencies
        are handled by :meth:`_get_stage_runtime_dependencies_commands`.

        The whole block is guarded on ``ROS_DISTRO`` being set, since rosdep
        cannot resolve dependencies without a ROS distribution.
        """
        return [
            "##[rockcraft.colcon] Installing build dependencies with rosdep",
            'if [ -n "${ROS_DISTRO:-}" ]; then',
            # rosdep must be initialized once; `rosdep init` creates the default
            # sources list, which is shared system-wide.
            "if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then",
            "rosdep init",
            "fi",
            'rosdep update --include-eol-distros --rosdistro "${ROS_DISTRO}"',
            # Resolve and install only the build-time dependencies declared in
            # the package.xml files found under the part's source directory.
            "rosdep install"
            " --default-yes"
            " --ignore-packages-from-source"
            " --dependency-types=buildtool"
            " --dependency-types=build"
            " --dependency-types=buildtool_export"
            " --dependency-types=build_export"
            ' --rosdistro "${ROS_DISTRO}"'
            ' --from-paths "${CRAFT_PART_SRC_WORK}"',
            "fi",
            "",
        ]

    @override
    def _get_source_command(self, path: str) -> list[str]:
        """Return the command to source the ROS environment.

        The ament setup scripts are not safe to source under ``set -u`` (they
        rely on several unset variables), so ``nounset`` is disabled around the
        sourcing and restored afterwards.
        """
        wspath = f"{path}/opt/ros/${{ROS_DISTRO:-}}"
        return [
            f'if [ -n "${{ROS_DISTRO:-}}" ] && [ -f "{wspath}/local_setup.sh" ]; then',
            "set +u",
            f'AMENT_CURRENT_PREFIX="{wspath}" . "{wspath}/local_setup.sh"',
            "set -u",
            "fi",
        ]

    def _get_stage_runtime_dependencies_commands(self) -> list[str]:
        """Return the commands that stage runtime dependencies with rosdep.

        The runtime dependencies declared in the workspace's ``package.xml``
        files are resolved to apt packages and unpacked into the part's install
        directory so they are primed into the rock. The resolution is performed
        by the :mod:`rockcraft.plugins._ros` helper module, which is run with a
        clean environment to avoid leaking the colcon build environment into the
        rosdep and apt invocations.

        The block is guarded on ``ROS_DISTRO`` being set, since rosdep cannot
        resolve dependencies without a ROS distribution.
        """
        # Re-run the helper with a minimal, explicit environment so that the
        # sourced ROS workspace does not interfere with rosdep and apt.
        env = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        for key in (
            "PATH",
            "SNAP",
            "SNAP_ARCH",
            "SNAP_NAME",
            "SNAP_VERSION",
            "http_proxy",
            "https_proxy",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        env_flags = [f"{key}={shlex.quote(value)}" for key, value in env.items()]

        stage_command = " ".join(
            [
                "env",
                "-i",
                *env_flags,
                sys.executable,
                "-I",
                "-m",
                "rockcraft.plugins._ros",
                "--part-src",
                '"${CRAFT_PART_SRC_WORK}"',
                "--part-install",
                '"${CRAFT_PART_INSTALL}"',
                "--ros-version",
                '"${ROS_VERSION}"',
                "--ros-distro",
                '"${ROS_DISTRO}"',
                "--target-arch",
                '"${CRAFT_TARGET_ARCH}"',
                "--stage-cache-dir",
                str(self._part_info.cache_dir.resolve()),
                "--base",
                str(self._part_info.base),
            ]
        )

        return [
            "##[rockcraft.colcon] Staging runtime dependencies with rosdep",
            'if [ -n "${ROS_DISTRO:-}" ]; then',
            stage_command,
            "fi",
            "",
        ]
