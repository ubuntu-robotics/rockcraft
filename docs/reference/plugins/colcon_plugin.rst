.. meta::
    :description: Reference documentation for the colcon plugin.

.. _rockcraft_colcon_plugin:

colcon plugin
=============

The colcon plugin builds `ROS 2 <https://docs.ros.org>`_ packages using the
`colcon <https://colcon.readthedocs.io>`_ meta build tool.

The :ref:`ROS 2 extensions <reference-extensions-ros2>` set up the requirements below
for you.

Requirements
------------

- ``ROS_DISTRO`` must be set in the part's ``build-environment``. The build
  fails if it is unset.
- The `ROS 2 apt repository <http://packages.ros.org/ros2/ubuntu>`_ for the
  Ubuntu release of the build must be added with a top-level
  ``package-repositories`` entry, so that rosdep can resolve dependencies.


Build behavior
--------------

The plugin does the following:

#. Installs the build tools: ``gcc``, ``g++``, ``cmake``, ``make``, ``rosdep``
   and the ``colcon`` packages, including the ``colcon-ros`` extension.
#. Installs the *build-time* dependencies of the packages with
   `rosdep <https://docs.ros.org/en/independent/api/rosdep/html/>`_, using the
   ``package.xml`` files in the workspace.
#. Sources the underlay at ``/opt/ros/$ROS_DISTRO``, if present.
#. Runs ``colcon build`` with ``--merge-install``, installing the workspace
   into ``/opt/ros/overlay`` of the part's install directory.
#. Rewrites the build-time install prefix to ``/opt/ros/overlay`` in the text
   files that colcon generates (the ``setup.*`` and ``local_setup.*`` scripts),
   so that the overlay can be sourced from its final location.
#. Resolves the *runtime* dependencies from the ``package.xml`` files to apt
   packages and unpacks them into the part's install directory, so that they
   are primed into the rock.

Because rosdep handles both kinds of dependencies, the ROS 2 dependencies of
your packages don't need to be listed in ``build-packages`` or
``stage-packages``.


Workspace layout
----------------

The built workspace is an *overlay* on top of the ROS 2 *underlay*.

.. list-table::
    :header-rows: 1

    * - Item
      - Path
    * - Underlay
      - ``/opt/ros/$ROS_DISTRO``
    * - Overlay
      - ``/opt/ros/overlay``
    * - Built executables
      - ``/opt/ros/overlay/lib/<package>``


Run the built workspace
-----------------------

The libraries in ``/opt/ros/overlay/lib`` and ``/opt/ros/$ROS_DISTRO/lib`` are
not in the default library search path. A command that runs the built
executables must first source the underlay and then the overlay:

.. code-block:: sh

    . /opt/ros/$ROS_DISTRO/setup.sh
    . /opt/ros/overlay/local_setup.sh

The ``ros2-source`` wrapper of the
:ref:`ROS 2 extensions <reference-extensions-ros2>` does this and then runs the
command it's given. If the rock has no ``/opt/ros/$ROS_DISTRO`` underlay, it
sources only the overlay.

The ``ros2`` wrapper, provided by the same extensions, does the same and runs
the ``ros2`` command-line tool, so that a service can use
``ros2 run <package> <executable>`` as its command.

Keys
----

This plugin provides the following unique keys.

colcon-packages
~~~~~~~~~~~~~~~
**Type:** list of strings

The colcon packages to build. If set, these are passed to ``colcon build`` as
``--packages-select``. If unset, all packages found in the source tree are
built.
The build-time and runtime dependencies are only resolved for these packages.

colcon-packages-ignore
~~~~~~~~~~~~~~~~~~~~~~~
**Type:** list of strings

The colcon packages to ignore during the build. These are passed to
``colcon build`` as ``--packages-ignore``.
The build-time and runtime dependencies of these packages are not resolved.

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
for the Lyrical distribution on the ``ubuntu@26.04`` base:

.. code-block:: yaml

    package-repositories:
      - type: apt
        url: http://packages.ros.org/ros2/ubuntu
        components: [main]
        suites: [resolute]
        key-id: C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654

    parts:
      demo-nodes:
        plugin: colcon
        source: https://github.com/ros2/demos.git
        source-branch: lyrical
        colcon-packages: [demo_nodes_cpp]
        build-environment:
          - ROS_DISTRO: lyrical

The build dependencies (``ros-lyrical-ament-cmake``, ``ros-lyrical-rclcpp``, and so
on) are resolved and installed automatically by rosdep from the package's
``package.xml``, and the runtime dependencies are resolved and staged the same
way, so neither needs to appear in ``build-packages`` or ``stage-packages``.
