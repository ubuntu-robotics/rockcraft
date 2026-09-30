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

The runtime dependencies of a ROS 2 workspace are only known at build time,
once the workspace sources (and their ``package.xml`` files) have been pulled.
This module is therefore run at build time:
:func:`stage_runtime_dependencies_callback` is registered as a craft-parts
``PRE_ORGANIZE`` callback for the build step of colcon parts (see
:mod:`rockcraft.services.lifecycle`), and runs in-process in the build
environment right after the colcon build installed the workspace.

The ``exec_depends`` declared in the workspace's ``package.xml`` files are
resolved to apt packages with rosdep, fetched as stage packages (together with
their transitive apt dependencies) and unpacked into the part's install
directory so they are primed into the rock.
"""

import logging
import pathlib
import re
import subprocess

from catkin_pkg import packages as catkin_packages
from craft_parts.infos import StepInfo
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
    *,
    part_src: str,
    part_install: str,
    ros_version: str,
    ros_distro: str,
    packages: list[str] | None = None,
) -> set[str]:
    """Resolve the runtime apt dependencies of the workspace with rosdep.

    The ``exec_depends`` of every package found under ``part_src`` are evaluated
    against the current ROS distribution and resolved to apt package names.
    Dependencies that are provided by another package in the workspace itself
    (i.e. already present under ``part_install``) are skipped.

    If *packages* is given, only packages whose name appears in that list are
    processed (mirrors the ``colcon-packages`` selection used at build time).
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
    packages: list[str] | None = None,
) -> None:
    """Stage the runtime dependencies of the ROS workspace using rosdep."""
    logger.info("Staging runtime dependencies...")

    apt_packages = _resolve_apt_dependencies(
        part_src=part_src,
        part_install=part_install,
        ros_version=ros_version,
        ros_distro=ros_distro,
        packages=packages,
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


def stage_runtime_dependencies_callback(
    step_info: StepInfo, *, packages: list[str] | None = None
) -> bool:
    """Stage the ROS 2 runtime dependencies of a colcon part.

    This is a craft-parts step callback meant to be registered for the build
    step at the ``PRE_ORGANIZE`` hook point (see
    :mod:`rockcraft.services.lifecycle`). It runs in-process, in the build
    environment, right after the part's build script completed, so the
    workspace sources (and their ``package.xml`` files) have been pulled and
    the colcon build installed the workspace into the part's install
    directory.

    ``ROS_DISTRO`` is read from the part's build step environment (the
    ``environment.sh`` that craft-parts generates for the build script); it is
    *not* present in this process' own environment, which is merely the
    environment rockcraft itself runs with. If ``ROS_DISTRO`` is not set the
    staging is skipped with a warning, since rosdep cannot resolve
    dependencies without a ROS distribution.

    :param step_info: The step information passed by craft-parts.
    :param packages: Limit staging to these ROS package names (mirrors the
        ``colcon-packages`` selection used at build time).
    :return: True, per the step callback convention.
    """
    environment = _read_step_environment(step_info)
    ros_distro = environment.get("ROS_DISTRO", "")
    if not ros_distro:
        logger.warning(
            "ROS_DISTRO is not set; skipping ROS 2 runtime dependency staging. "
            "Set ROS_DISTRO in the part build-environment (or add a ros2-* "
            "extension) so rosdep can resolve dependencies."
        )
        return True

    stage_runtime_dependencies(
        part_src=str(step_info.part_src_subdir),
        part_install=str(step_info.part_install_dir),
        ros_version=environment.get("ROS_VERSION", "2"),
        ros_distro=ros_distro,
        target_arch=step_info.target_arch,
        stage_cache_dir=str(step_info.cache_dir),
        base=str(step_info.project_info.base),
        packages=packages,
    )

    _fix_library_alternatives(part_install=str(step_info.part_install_dir))

    return True


def _read_step_environment(step_info: StepInfo) -> dict[str, str]:
    """Read the environment generated for the part's build step.

    craft-parts writes the step environment to ``environment.sh`` in the
    part's run directory right before executing the build script. The file is
    a series of ``export KEY="value"`` lines covering the application, part,
    plugin and user (``build-environment``) environment. It is sourced by the
    build script but is *not* exported into the environment of the process
    running the lifecycle, so it is read back here.
    """
    environment: dict[str, str] = {}
    # The part's run directory is a sibling of its state directory.
    environment_file = step_info.part_state_dir.parent / "run" / "environment.sh"
    try:
        lines = environment_file.read_text().splitlines()
    except FileNotFoundError:
        logger.debug("No build step environment file at %s", environment_file)
        return environment

    for line in lines:
        match = re.fullmatch(r'export ([A-Za-z_][A-Za-z0-9_]*)="(.*)"', line)
        if match:
            environment[match.group(1)] = match.group(2)

    return environment


def _fix_library_alternatives(part_install: str) -> None:
    """Restore the BLAS/LAPACK SONAME symlinks in the part's install directory.

    ``libblas3`` and ``liblapack3`` install their libraries into provider
    subdirectories (``blas/`` and ``lapack/``) and rely on their ``postinst``
    running ``update-alternatives`` to create the canonical SONAME symlink
    (e.g. ``libblas.so.3``) in the default linker search path. Staging
    packages unpacks the files but never runs maintainer scripts, so that
    symlink is missing and the dynamic linker cannot find the libraries (which
    breaks ``rclpy``/numpy and any node that links BLAS/LAPACK). Recreate the
    symlink with a relative target so it survives the install -> prime -> rock
    relocation.
    """
    install_path = pathlib.Path(part_install)
    for provider in ("blas", "lapack"):
        for library in install_path.glob(f"usr/lib/*/{provider}/lib*.so.*"):
            soname_link = library.parent.parent / library.name
            if not soname_link.exists():
                logger.debug(
                    "Restoring SONAME symlink %s -> %s/%s",
                    soname_link,
                    provider,
                    library.name,
                )
                soname_link.symlink_to(f"{provider}/{library.name}")
