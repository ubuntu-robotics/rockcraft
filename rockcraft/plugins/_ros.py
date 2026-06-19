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

"""Stage ROS 2 runtime dependencies of a colcon workspace with rosdep.

This module is executed as a script from the colcon plugin's build step
(``python -m rockcraft.plugins._ros``) because the runtime dependencies of a
ROS 2 workspace are only known at build time, once the workspace sources (and
their ``package.xml`` files) have been pulled.

The ``exec_depends`` declared in the workspace's ``package.xml`` files are
resolved to apt packages with rosdep, fetched as stage packages (together with
their transitive apt dependencies) and unpacked into the part's install
directory so they are primed into the rock.
"""

import argparse
import logging
import pathlib
import subprocess
import sys

from catkin_pkg import packages as catkin_packages
from craft_parts.packages import Repository

from rockcraft.errors import RockcraftError

logger = logging.getLogger(__name__)


class RosdepError(RockcraftError):
    """Base class for rosdep errors."""


class RosdepUnexpectedResultError(RosdepError):
    """Error for unexpected rosdep results."""

    def __init__(self, dependency: str, output: str) -> None:
        super().__init__(
            message=(
                "Received unexpected result from rosdep when trying to resolve "
                f"{dependency!r}:\n{output}"
            )
        )


def _parse_rosdep_resolve_dependencies(
    dependency_name: str, output: str
) -> dict[str, set[str]]:
    """Parse the output of ``rosdep resolve`` into a mapping of installers.

    The output of ``rosdep resolve`` follows the pattern::

        # apt
        package1
        package2
        # pip
        pip - package1

    These are split out into a dict of installer (e.g. ``apt`` or ``pip``) to
    the set of package names for that installer.
    """
    dependencies: dict[str, set[str]] = {}
    dependency_set: set[str] | None = None
    # Parse line by line: lines starting with ``#`` are installer headers (the
    # ``#`` may or may not be followed by a space), and every other non-empty
    # line lists one or more whitespace-separated package names.
    for line in output.splitlines():
        entry = line.strip()
        if not entry:
            continue
        if entry.startswith("#"):
            key = entry[1:].strip()
            dependencies[key] = set()
            dependency_set = dependencies[key]
        else:
            if dependency_set is None:
                raise RosdepUnexpectedResultError(dependency_name, output)
            dependency_set.update(entry.split())

    return dependencies


def _resolve_apt_dependencies(
    *, part_src: str, part_install: str, ros_version: str, ros_distro: str
) -> set[str]:
    """Resolve the runtime apt dependencies of the workspace with rosdep.

    The ``exec_depends`` of every package found under ``part_src`` are evaluated
    against the current ROS distribution and resolved to apt package names.
    Dependencies that are provided by another package in the workspace itself
    (i.e. already present under ``part_install``) are skipped.
    """
    apt_packages: set[str] = set()

    installed_pkgs = catkin_packages.find_packages(part_install).values()
    installed_names = {pkg.name for pkg in installed_pkgs}

    for pkg in catkin_packages.find_packages(part_src).values():
        if packages is not None and pkg.name not in packages:
            continue
        # Evaluate the conditions of all dependencies.
        pkg.evaluate_conditions(
            {
                "ROS_VERSION": ros_version,
                "ROS_DISTRO": ros_distro,
                "ROS_PYTHON_VERSION": "3",
            }
        )
        # Retrieve only the 'exec_depends' whose condition is true.
        for dep in (
            exec_dep for exec_dep in pkg.exec_depends if exec_dep.evaluated_condition
        ):
            # No need to resolve this dependency if it is a local package.
            if dep.name in installed_names:
                continue

            cmd = ["rosdep", "resolve", dep.name, "--rosdistro", ros_distro]
            logger.info("Running %r", cmd)
            try:
                proc = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as error:
                raise RosdepError(
                    message=(
                        f"Failed to resolve the runtime dependency {dep.name!r} "
                        f"for ROS distro {ros_distro!r}."
                    ),
                    details=(
                        f"rosdep stdout: {error.stdout.decode().strip()}\n"
                        f"rosdep stderr: {error.stderr.decode().strip()}"
                    ),
                    resolution=(
                        f"Ensure {dep.name!r} is declared correctly in the "
                        "package.xml and is published in rosdistro for "
                        f"{ros_distro!r}. If it is a system package, check that "
                        "the ROS 2 apt repository is configured (e.g. by adding "
                        "the matching ros2-* extension)."
                    ),
                ) from error

            parsed = _parse_rosdep_resolve_dependencies(
                dep.name, proc.stdout.decode().strip()
            )
            apt_packages |= parsed.pop("apt", set())

            if parsed:  # still non-empty after removing apt packages
                logger.warning("Unhandled non-apt dependencies: %r", parsed)

    return apt_packages


def stage_runtime_dependencies(
    *,
    part_src: str,
    part_install: str,
    ros_version: str,
    ros_distro: str,
    target_arch: str,
    stage_cache_dir: str,
    base: str,
) -> None:
    """Stage the runtime dependencies of the ROS workspace using rosdep."""
    logger.info("Staging runtime dependencies...")

    apt_packages = _resolve_apt_dependencies(
        part_src=part_src,
        part_install=part_install,
        ros_version=ros_version,
        ros_distro=ros_distro,
    )

    if not apt_packages:
        logger.info("No runtime dependencies to stage.")
        return

    package_names = sorted(apt_packages)
    install_path = pathlib.Path(part_install)
    stage_packages_path = install_path.parent / "stage_packages"

    Repository.configure("rockcraft")

    logger.info("Fetching stage packages: %r", package_names)
    fetched_stage_packages = Repository.fetch_stage_packages(
        cache_dir=pathlib.Path(stage_cache_dir),
        package_names=package_names,
        arch=target_arch,
        base=base,
        stage_packages_path=stage_packages_path,
    )

    logger.info("Unpacking stage packages: %r", fetched_stage_packages)
    Repository.unpack_stage_packages(
        stage_packages_path=stage_packages_path, install_path=install_path
    )


def main(argv: list[str] | None = None) -> int:
    """Run the runtime dependency staging from the command line."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--part-src", required=True)
    parser.add_argument("--part-install", required=True)
    parser.add_argument("--ros-version", required=True)
    parser.add_argument("--ros-distro", required=True)
    parser.add_argument("--target-arch", required=True)
    parser.add_argument("--stage-cache-dir", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)

    try:
        stage_runtime_dependencies(
            part_src=args.part_src,
            part_install=args.part_install,
            ros_version=args.ros_version,
            ros_distro=args.ros_distro,
            target_arch=args.target_arch,
            stage_cache_dir=args.stage_cache_dir,
            base=args.base,
        )
    except RockcraftError as error:
        # This module runs as a subprocess of the colcon plugin build step;
        # surface a clean, actionable message instead of a raw Python traceback
        # (hence logging.error rather than logging.exception).
        lines = [f"Error: {error}"]
        if error.details:
            lines.append(f"Details: {error.details}")
        if error.resolution:
            lines.append(f"Recommended resolution: {error.resolution}")
        logger.error("\n".join(lines))  # noqa: TRY400
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
