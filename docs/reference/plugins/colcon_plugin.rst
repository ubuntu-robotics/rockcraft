.. meta::
    :description: Reference documentation for the colcon plugin.

.. _rockcraft_colcon_plugin:

colcon plugin
=============

The colcon plugin builds `ROS 2 <https://docs.ros.org>`_ packages using the
`colcon <https://colcon.readthedocs.io>`_ meta build tool.

The plugin runs ``colcon build`` with ``--merge-install``, installing the built
workspace into the part's install directory. The required build tools
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

    rosdep resolution requires ``ROS_DISTRO`` to be set in the part's
    ``build-environment`` and the matching ROS 2 apt repository to be
    configured. The :ref:`ROS 2 extensions <reference-extensions>` set both up
    for you.

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

If ``ROS_DISTRO`` is set and an underlay workspace is present at
``/opt/ros/$ROS_DISTRO``, the plugin sources it before building. Set
``ROS_DISTRO`` through the part's ``build-environment`` to match the ROS 2
distribution being built.


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
