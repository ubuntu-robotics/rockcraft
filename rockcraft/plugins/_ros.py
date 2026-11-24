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
:func:`stage_runtime_dependencies_callback` is called by the ``post_build`` hook
of the colcon plugin (see :mod:`rockcraft.plugins.colcon_plugin`), which the
lifecycle service runs as a craft-parts ``PRE_ORGANIZE`` callback (see
:mod:`rockcraft.services.lifecycle`), in-process in the build
environment right after the colcon build installed the workspace.

The ``exec_depends`` declared in the workspace's ``package.xml`` files are
resolved to apt packages with rosdep, fetched as stage packages (together with
their transitive apt dependencies) and merged into the part's install
directory, without overwriting what is already there, so they are primed into
the rock. Only these packages are normalized (see
:func:`craft_parts.packages.normalize.normalize`), not what the build installed.
"""

import logging
import pathlib
import re
import subprocess
import tempfile
from collections.abc import Mapping

from catkin_pkg import packages as catkin_packages
from craft_parts.infos import StepInfo
from craft_parts.packages import Repository
from craft_parts.utils import file_utils

from rockcraft.errors import RockcraftError

logger = logging.getLogger(__name__)

_ROSDEP_KEY_HEADER = re.compile(r"#ROSDEP\[(.+)\]")


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


def _parse_rosdep_resolve_batch(
    dependency_names: list[str], output: str
) -> dict[str, dict[str, set[str]]]:
    """Parse the output of ``rosdep resolve`` called with several keys.

    With more than one key, ``rosdep resolve`` prefixes the result of each key
    with a ``#ROSDEP[<key>]`` line::

        # ROSDEP[key1]
        # apt
        package1
        # ROSDEP[key2]
        # apt
        package2

    A key that rosdep fails to resolve has an empty section. With a single key
    there is no such prefix, and the whole output belongs to that key.

    The result maps each key to its installer -> packages mapping, as returned
    by :func:`_parse_rosdep_resolve_dependencies`.
    """
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in output.splitlines():
        header = _ROSDEP_KEY_HEADER.fullmatch(line.strip())
        if header:
            current = sections.setdefault(header.group(1), [])
        elif current is not None:
            current.append(line)
        elif line.strip():
            if len(dependency_names) != 1:
                raise RosdepUnexpectedResultError(", ".join(dependency_names), output)
            # A lone key is reported without a header.
            current = sections.setdefault(dependency_names[0], [])
            current.append(line)

    return {
        key: _parse_rosdep_resolve_dependencies(key, "\n".join(lines))
        for key, lines in sections.items()
    }


def _resolve_apt_dependencies(
    *,
    part_src: str,
    part_install: str,
    ros_version: str,
    ros_distro: str,
    colcon_packages: list[str] | None = None,
    colcon_packages_ignore: list[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> set[str]:
    """Resolve the runtime apt dependencies of the workspace with rosdep.

    The ``exec_depends`` of every package found under ``part_src`` are evaluated
    against the current ROS distribution and resolved to apt package names.
    Dependencies that are provided by another package in the workspace itself
    (i.e. already present under ``part_install``) are skipped.

    If *colcon_packages* is given, only packages whose name appears in that list
    are processed (mirrors the ``colcon-packages`` selection used at build
    time). Packages listed in *colcon_packages_ignore* are never processed
    (mirrors ``colcon-packages-ignore``).

    *environment* is the environment of the build script. It is the one rosdep
    runs with, so that it finds the cache populated by the build's
    ``rosdep update`` (see ``ROS_HOME``), and it provides ``ROS_PYTHON_VERSION``.
    """
    apt_packages: set[str] = set()
    ros_python_version = (environment or {}).get("ROS_PYTHON_VERSION", "3")

    installed_pkgs = catkin_packages.find_packages(part_install).values()
    installed_names = {pkg.name for pkg in installed_pkgs}

    # Collect the unique dependency names first, so that each one is resolved
    # (a subprocess call) only once, however many packages depend on it.
    dependency_names: set[str] = set()
    for pkg in catkin_packages.find_packages(part_src).values():
        if colcon_packages is not None and pkg.name not in colcon_packages:
            continue
        if colcon_packages_ignore and pkg.name in colcon_packages_ignore:
            continue
        # Evaluate the conditions of all dependencies.
        pkg.evaluate_conditions(
            {
                "ROS_VERSION": ros_version,
                "ROS_DISTRO": ros_distro,
                "ROS_PYTHON_VERSION": ros_python_version,
            }
        )
        # Retrieve only the 'exec_depends' whose condition is true.
        for dep in (
            exec_dep for exec_dep in pkg.exec_depends if exec_dep.evaluated_condition
        ):
            # No need to resolve this dependency if it is a local package.
            if dep.name not in installed_names:
                dependency_names.add(dep.name)

    if not dependency_names:
        return apt_packages

    # A single rosdep call resolves all the keys: each call has a significant
    # start-up cost, which adds up quickly with one call per dependency.
    names = sorted(dependency_names)
    cmd = ["rosdep", "resolve", *names, "--rosdistro", ros_distro]
    logger.info("Running %r", cmd)
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            env=dict(environment) if environment else None,
        )
    except subprocess.CalledProcessError as error:
        stdout = error.stdout.decode().strip()
        # rosdep still reports the keys it could resolve: the failed ones are
        # those left without any result.
        try:
            resolved = _parse_rosdep_resolve_batch(names, stdout)
        except RosdepUnexpectedResultError:
            resolved = {}
        failed = [name for name in names if not resolved.get(name)] or names
        raise RosdepError(
            message=(
                f"Failed to resolve the runtime dependencies {failed!r} "
                f"for ROS distro {ros_distro!r}."
            ),
            details=(
                f"rosdep stdout: {stdout}\n"
                f"rosdep stderr: {error.stderr.decode().strip()}"
            ),
            resolution=(
                f"Ensure {failed!r} are declared correctly in the "
                "package.xml and are published in rosdistro for "
                f"{ros_distro!r}. If they are system packages, check that "
                "the ROS 2 apt repository is configured (e.g. by adding "
                "the matching ros2-* extension)."
            ),
        ) from error

    resolved = _parse_rosdep_resolve_batch(names, proc.stdout.decode().strip())
    for name in names:
        parsed = resolved.get(name, {})
        apt_packages |= parsed.pop("apt", set())

        if parsed:  # still non-empty after removing apt packages
            logger.warning("Unhandled non-apt dependencies of %r: %r", name, parsed)

    return apt_packages


def _get_unpacked_stage_packages(part_install: pathlib.Path) -> set[str]:
    """Return the names of the packages craft-parts already unpacked for the part.

    The debs of the part's own ``stage-packages``, with their dependencies, are
    kept in the part's ``stage_packages`` directory and were unpacked into the
    install directory at the start of the build.
    """
    stage_packages_dir = part_install.parent / "stage_packages"
    # apt names the archives <package>_<version>_<arch>.deb
    return {deb.name.split("_", 1)[0] for deb in stage_packages_dir.glob("*.deb")}


def _merge_without_overwriting(source: pathlib.Path, destination: pathlib.Path) -> None:
    """Merge the *source* tree into *destination*, keeping what already exists.

    Directories are merged, and so is their metadata: the existing ones keep
    theirs. A file or symlink of *source* is skipped if *destination* already
    has an entry at that path.
    """

    def ignore_existing(directory: str, names: list[str]) -> list[str]:
        destination_dir = destination / pathlib.Path(directory).relative_to(source)
        ignored = []
        for name in names:
            entry = pathlib.Path(directory, name)
            if entry.is_dir() and not entry.is_symlink():
                continue
            target = destination_dir / name
            if target.is_symlink() or target.exists():
                ignored.append(name)
        return ignored

    file_utils.link_or_copy_tree(
        source, destination, ignore=ignore_existing, overwrite_metadata=False
    )


def stage_runtime_dependencies(  # noqa: PLR0913 (too many arguments)
    *,
    part_src: str,
    part_install: str,
    ros_version: str,
    ros_distro: str,
    target_arch: str,
    stage_cache_dir: str,
    base: str,
    colcon_packages: list[str] | None = None,
    colcon_packages_ignore: list[str] | None = None,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Stage the runtime dependencies of the ROS workspace using rosdep."""
    logger.info("Staging runtime dependencies...")

    apt_packages = _resolve_apt_dependencies(
        part_src=part_src,
        part_install=part_install,
        ros_version=ros_version,
        ros_distro=ros_distro,
        colcon_packages=colcon_packages,
        colcon_packages_ignore=colcon_packages_ignore,
        environment=environment,
    )

    if not apt_packages:
        logger.info("No runtime dependencies to stage.")
        return

    package_names = sorted(apt_packages)
    install_path = pathlib.Path(part_install)

    Repository.configure("rockcraft")

    # The pull-owned stage_packages directory of the part is not reused: it
    # outlives a build clean and is unpacked again at the start of every build,
    # so stale runtime packages would come back. The downloads are cached in
    # stage_cache_dir, so this directory only holds links to them.
    #
    # The packages are unpacked in a scratch directory first, as unpacking
    # normalizes the files (shebangs, absolute symlinks, ...): that must not
    # alter what the build installed. They are then merged into the install
    # directory without overwriting what is already there.
    with (
        tempfile.TemporaryDirectory(
            suffix="ros-runtime-debs", dir=install_path.parent
        ) as runtime_debs,
        tempfile.TemporaryDirectory(
            suffix="ros-runtime-unpack", dir=install_path.parent
        ) as runtime_unpack,
    ):
        stage_packages_path = pathlib.Path(runtime_debs)
        unpack_path = pathlib.Path(runtime_unpack)

        logger.info("Fetching stage packages: %r", package_names)
        fetched_stage_packages = Repository.fetch_stage_packages(
            cache_dir=pathlib.Path(stage_cache_dir),
            package_names=package_names,
            arch=target_arch,
            base=base,
            stage_packages_path=stage_packages_path,
            # Do not unpack again over the install directory what the part's own
            # stage-packages already provide, as that would overwrite the edits
            # of an override-build. Only the deb repository supports the filter.
            packages_filters=_get_unpacked_stage_packages(install_path),  # ty: ignore[unknown-argument]
        )

        logger.info("Unpacking stage packages: %r", fetched_stage_packages)
        Repository.unpack_stage_packages(
            stage_packages_path=stage_packages_path, install_path=unpack_path
        )
        _merge_without_overwriting(unpack_path, install_path)


def stage_runtime_dependencies_callback(
    step_info: StepInfo,
    *,
    colcon_packages: list[str] | None = None,
    colcon_packages_ignore: list[str] | None = None,
) -> bool:
    """Stage the ROS 2 runtime dependencies of a colcon part.

    This is a craft-parts step callback, called at the build step's
    ``PRE_ORGANIZE`` hook point by the colcon plugin's ``post_build`` hook (see
    :mod:`rockcraft.plugins.colcon_plugin`). It runs in-process, in the build
    environment, right after the part's build script completed, so the
    workspace sources (and their ``package.xml`` files) have been pulled and
    the colcon build installed the workspace into the part's install
    directory.

    ``ROS_DISTRO`` is read from the part's build step environment (the
    ``environment.sh`` that craft-parts generates for the build script, evaluated
    by a shell); it is *not* present in this process' own environment, which is
    merely the environment rockcraft itself runs with. If ``ROS_DISTRO`` is not
    set the staging is skipped with a warning, since rosdep cannot resolve
    dependencies without a ROS distribution.

    :param step_info: The step information passed by craft-parts.
    :param colcon_packages: Limit staging to these ROS package names (mirrors
        the ``colcon-packages`` selection used at build time).
    :param colcon_packages_ignore: Do not stage the dependencies of these ROS
        package names (mirrors ``colcon-packages-ignore``).
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
        colcon_packages=colcon_packages,
        colcon_packages_ignore=colcon_packages_ignore,
        environment=environment,
    )

    _fix_library_alternatives(part_install=str(step_info.part_install_dir))

    return True


def _read_step_environment(step_info: StepInfo) -> dict[str, str]:
    """Return the environment the part's build script ran with.

    craft-parts writes the step environment to ``environment.sh`` in the
    part's run directory right before executing the build script. It is a shell
    script whose ``export`` values may reference other variables (e.g.
    ``ROS_DISTRO: ${CHOSEN_DISTRO}``), so a shell evaluates it, as for the
    build script. The result is not exported into the environment of the
    process running the lifecycle, hence it is computed here.
    """
    # The part's run directory is a sibling of its state directory.
    environment_file = step_info.part_state_dir.parent / "run" / "environment.sh"
    if not environment_file.is_file():
        logger.debug("No build step environment file at %s", environment_file)
        return {}

    result = subprocess.run(
        ["/bin/bash", "-c", '. "$1" && env -0', "_", str(environment_file)],
        check=True,
        capture_output=True,
    )
    return dict(
        item.split("=", 1) for item in result.stdout.decode().split("\0") if "=" in item
    )


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
                # A dangling link (e.g. into /etc/alternatives) is replaced.
                soname_link.unlink(missing_ok=True)
                soname_link.symlink_to(f"{provider}/{library.name}")
