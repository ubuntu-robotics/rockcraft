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

"""Extensions for ROS 2 projects built with the colcon plugin."""

import abc
from typing import Any

from craft_cli import emit
from typing_extensions import override

from .extension import Extension, get_extensions_data_dir

_ROS2_APT_KEY_ID = "C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654"
_ROS2_APT_URL = "http://packages.ros.org/ros2/ubuntu"


class _ROS2Base(Extension):
    """Base class for ROS 2 extensions.

    Each concrete subclass targets one ROS 2 distribution / Ubuntu base pair.
    The extension automatically:

    * Adds the ROS 2 apt repository to ``package-repositories``.
    * Injects ``ROS_DISTRO`` into the ``build-environment`` of every user part,
      so the :ref:`colcon plugin <rockcraft_colcon_plugin>` can source the
      correct underlay workspace.
    """

    @property
    @abc.abstractmethod
    def distro(self) -> str:
        """Return the ROS 2 distribution name, e.g. ``'humble'``."""

    @property
    @abc.abstractmethod
    def suite(self) -> str:
        """Return the Ubuntu suite codename, e.g. ``'jammy'``."""

    @classmethod
    def _expected_base(cls) -> str:
        """Return the Ubuntu base this extension targets, e.g. ``'ubuntu@22.04'``.

        Derived from :meth:`get_supported_bases`, whose first ``@``-form entry
        is the targeted base (``bare`` and the deprecated ``ubuntu:X.Y`` alias
        are skipped).
        """
        return next(b for b in cls.get_supported_bases() if "@" in b)

    @override
    def _validate_extras(self, extension_name: str) -> None:
        """Check that a set ``build-base`` matches the extension's base.

        The ROS 2 apt repository targets one Ubuntu suite, so the build
        environment must run that suite. Mixing bases and build-bases is not
        allowed: whenever ``build-base`` is set it must equal the targeted
        base. When it is unset it defaults to the base, which is already
        validated against :meth:`get_supported_bases`.
        """
        base: str | None = self.yaml_data.get("base")
        if base == "bare":
            build_base: str | None = self.yaml_data.get("build-base")
            expected_base = self._expected_base()

            if build_base != expected_base:
                raise errors.ExtensionError(
                    f"Extension {extension_name!r} targets {expected_base!r} "
                    f"(ROS 2 {self.distro} on the {self.suite!r} suite), but the project "
                    f"sets build-base {build_base!r}.",
                    resolution=(
                        f"Set 'build-base: {expected_base}' so the ROS 2 apt "
                        "repository matches the build environment."
                    ),
                )

    @staticmethod
    @override
    def is_experimental(base: str | None) -> bool:
        """Check if the extension is in an experimental state.

        The ROS 2 extensions are experimental while the colcon plugin and the
        launcher mechanism stabilise, so their behaviour may still change.
        """
        return True

    @override
    def get_root_snippet(self) -> dict[str, Any]:
        """Return the root snippet to apply.

        Adds the ROS 2 apt repository for the correct Ubuntu suite.
        """
        # The ros2-launch wrapper is an implicit runtime contract: ROS 2 service
        # and entrypoint commands must be run through it so the ROS 2 underlay
        # is sourced. Surface that here so the requirement is not invisible.
        emit.progress(
            f"ros2-{self.distro}: run ROS 2 service and entrypoint commands "
            "through the 'ros2-launch' wrapper so the ROS 2 environment is "
            'sourced at runtime, e.g. "command: ros2-launch ros2 run '
            '<package> <node>".',
            permanent=True,
        )
        return {
            "package-repositories": [
                {
                    "type": "apt",
                    "url": _ROS2_APT_URL,
                    "components": ["main"],
                    "suites": [self.suite],
                    "key-id": _ROS2_APT_KEY_ID,
                }
            ],
        }

    @override
    def get_part_snippet(self) -> dict[str, Any]:
        """Return the part snippet to apply to every existing part.

        Injects ``ROS_DISTRO`` into the part's ``build-environment`` so the
        colcon plugin sources the correct ROS 2 underlay.
        """
        return {
            "build-environment": [{"ROS_DISTRO": self.distro}],
        }

    @override
    def get_parts_snippet(self) -> dict[str, Any]:
        """Return the launcher part for the ROS 2 workspace.

        Injects a ``ros2-launch`` wrapper script (installed to
        ``/usr/bin/ros2-launch``) that sources the ROS 2 underlay and extends
        ``AMENT_PREFIX_PATH`` with the rock root before exec-ing the user
        command. This mirrors the ``command-chain`` launcher mechanism used by
        the equivalent snapcraft extensions.

        The part is named ``ros2-{distro}-launch`` (snapcraft uses a
        ``ros2-{distro}/ros2-launch`` slash-namespace, which rockcraft does not
        support).
        """
        return {
            f"ros2-{self.distro}-launch": {
                "plugin": "dump",
                "source": str(get_extensions_data_dir() / "ros2"),
                "organize": {"ros2-launch": "usr/bin/ros2-launch"},
                "stage": ["usr/bin/ros2-launch"],
                # libblas3/liblapack3 are undeclared runtime deps of rclpy on
                # all ROS 2 distros: rosidl_generator_py generates Python
                # message bindings that import numpy, which links against
                # BLAS/LAPACK.  These are absent from every package.xml so
                # rosdep cannot resolve them automatically.
                # "stage-packages": ["libblas3", "liblapack3"],
            },
        }


class ROS2HumbleExtension(_ROS2Base):
    """Extension for ROS 2 Humble Hawksbill on ubuntu@22.04."""

    @staticmethod
    @override
    def get_supported_bases() -> tuple[str, ...]:
        """Return supported bases."""
        return ("bare", "ubuntu@22.04", "ubuntu:22.04")

    @property
    @override
    def distro(self) -> str:
        return "humble"

    @property
    @override
    def suite(self) -> str:
        return "jammy"


class ROS2JazzyExtension(_ROS2Base):
    """Extension for ROS 2 Jazzy Jalisco on ubuntu@24.04."""

    @staticmethod
    @override
    def get_supported_bases() -> tuple[str, ...]:
        """Return supported bases."""
        return ("bare", "ubuntu@24.04", "ubuntu:24.04")

    @property
    @override
    def distro(self) -> str:
        return "jazzy"

    @property
    @override
    def suite(self) -> str:
        return "noble"


class ROS2LyricalExtension(_ROS2Base):
    """Extension for ROS 2 Lyrical Lizard on ubuntu@26.04."""

    @staticmethod
    @override
    def get_supported_bases() -> tuple[str, ...]:
        """Return supported bases."""
        return ("bare", "ubuntu@26.04", "ubuntu:26.04")

    @property
    @override
    def distro(self) -> str:
        return "lyrical"

    @property
    @override
    def suite(self) -> str:
        return "resolute"
