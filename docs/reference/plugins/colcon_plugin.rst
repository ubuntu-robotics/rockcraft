.. meta::
    :description: Reference documentation for the colcon plugin.

.. _rockcraft_colcon_plugin:

colcon plugin
=============

The colcon plugin builds `ROS 2 <https://docs.ros.org>`_ packages using the
`colcon <https://colcon.readthedocs.io>`_ meta build tool.

The plugin runs ``colcon build`` with ``--merge-install``, installing the built
workspace into ``/opt/ros/overlay`` of the part's install directory. The
workspace is an *overlay* on top of the ROS 2 *underlay* that is installed in
``/opt/ros/$ROS_DISTRO``, so the built executables are in
``/opt/ros/overlay/lib/<package>``. The plugin uses the ``colcon-ros`` extension
so that the build discovers the packages of the underlay and the overlay
chains on it. Because the workspace is built in the part's install directory,
the plugin rewrites the build-time install prefix to ``/opt/ros/overlay`` in
the text files that colcon generates (the ``setup.*`` and ``local_setup.*``
scripts), so that the overlay can be sourced from its final location.

To use the workspace, source the underlay's ``/opt/ros/$ROS_DISTRO/setup.sh``
and then the overlay's ``/opt/ros/overlay/local_setup.sh``, which does not chain
to the underlay, for example through the ``ros2`` or
``ros2-source`` wrappers of the :ref:`ROS 2 extensions <reference-extensions>`.
Commands that run the built executables must do this, because the libraries in
``/opt/ros/overlay/lib`` and ``/opt/ros/$ROS_DISTRO/lib`` are not in the
default library search path. The required build tools
(``gcc``, ``g++``, ``cmake`` and the ``colcon`` packages) are installed
automatically.

The plugin also uses `rosdep <https://docs.ros.org/en/independent/api/rosdep/html/>`_
to automatically install the *build-time* dependencies and stage the *runtime*
dependencies declared in the ``package.xml`` files in the workspace. This means the
ROS 2 build and runtime dependencies of your packages do not need to be listed
by hand in ``build-packages`` or ``stage-packages``. The runtime dependencies
are resolved to apt packages and unpacked into the part's install directory so
they are primed into the rock.

.. note::

    ``ROS_DISTRO`` must be set in the part's ``build-environment``, and the
    matching ROS 2 apt repository must be configured for rosdep to resolve
    dependencies. The build fails if ``ROS_DISTRO`` is unset. The
    :ref:`ROS 2 extensions <reference-extensions>` set both up for you.

.. note::

    ROS 2 packages are published for specific Ubuntu releases through the
    `ROS 2 apt repositories <http://packages.ros.org/ros2/ubuntu>`_. Add the
    relevant repository with a top-level ``package-repositories`` entry so that
    rosdep can resolve and install your project's ROS 2 dependencies.


Keys
----

This plugin provides the following unique keys.

colcon-packages
~~~~~~~~~~~~~~~
**Type:** list of strings

The colcon packages to build. If set, these are passed to ``colcon build`` as
``--packages-select``. If unset, all packages found in the source tree are
built.

colcon-packages-ignore
~~~~~~~~~~~~~~~~~~~~~~~
**Type:** list of strings

The colcon packages to ignore during the build. These are passed to
``colcon build`` as ``--packages-ignore``.

colcon-cmake-args
~~~~~~~~~~~~~~~~~
**Type:** list of strings

Custom CMake arguments passed to ``colcon build`` via ``--cmake-args``. Unless
the build type is set explicitly (for example by passing
``-DCMAKE_BUILD_TYPE=Debug``), the plugin builds in ``Release`` mode.


Environment variables
---------------------

This plugin sets the following environment variables in the build environment:

- ``AMENT_PYTHON_EXECUTABLE`` is set to ``/usr/bin/python3``.
- ``COLCON_PYTHON_EXECUTABLE`` is set to ``/usr/bin/python3``.
- ``ROS_VERSION`` is set to ``2``.
- ``ROS_PYTHON_VERSION`` is set to ``3``.

If an underlay workspace is present at ``/opt/ros/$ROS_DISTRO``, the plugin
sources it before building. Set ``ROS_DISTRO`` through the part's
``build-environment`` to match the ROS 2 distribution being built.


Example
-------

The following part builds the ``demo_nodes_cpp`` package from the ROS 2 demos
for the Jazzy distribution on the ``ubuntu@24.04`` base:

.. code-block:: yaml

    package-repositories:
      - type: apt
        url: http://packages.ros.org/ros2/ubuntu
        components: [main]
        suites: [noble]
        key-id: C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654

    parts:
      demo-nodes:
        plugin: colcon
        source: https://github.com/ros2/demos.git
        source-branch: jazzy
        colcon-packages: [demo_nodes_cpp]
        build-environment:
          - ROS_DISTRO: jazzy

The build dependencies (``ros-jazzy-ament-cmake``, ``ros-jazzy-rclcpp``, and so
on) are resolved and installed automatically by rosdep from the package's
``package.xml``, and the runtime dependencies are resolved and staged the same
way, so neither needs to appear in ``build-packages`` or ``stage-packages``.
