.. meta::
    :description: Release notes for Rockcraft 1.20.

.. _release-1.20:

Rockcraft 1.20 release notes
============================

**In development**

Learn about the new features, changes, and fixes introduced in Rockcraft 1.20.
For information about the Rockcraft release cycle, see the
:ref:`release_policy_and_schedule`.


Requirements and compatibility
------------------------------

To run Rockcraft, a system requires the following minimum hardware and
installed software. These requirements apply to local hosts as well as VMs and
container hosts.


Minimum hardware requirements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- AMD64, ARM64, ARMv7-M, RISC-V 64-bit, PowerPC 64-bit little-endian, or S390x
  processor
- 2GB RAM
- 10GB available storage space
- Internet access for remote software sources and the Snap Store


Platform requirements
~~~~~~~~~~~~~~~~~~~~~

.. list-table::
  :header-rows: 1
  :widths: 1 3 3

  * - Platform
    - Version
    - Software requirements
  * - GNU/Linux
    - Popular distributions that ship with systemd and are `compatible with
      snapd <https://snapcraft.io/docs/installing-snapd>`_
    - systemd


What's new
----------

Rockcraft 1.20 brings the following features, integrations, and improvements.


colcon plugin
~~~~~~~~~~~~~

The :ref:`rockcraft_colcon_plugin` builds `ROS 2 <https://docs.ros.org>`_ packages
using the `colcon <https://colcon.readthedocs.io>`_ meta build tool. It supports
all Ubuntu bases for which a ROS 2 distribution is available (ubuntu\@22.04,
ubuntu\@24.04, and ubuntu\@26.04) and handles sourcing of the ROS 2 underlay
workspace automatically. The build-time and runtime dependencies declared in
the workspace's ``package.xml`` files are resolved automatically with
``rosdep``, so they no longer need to be listed by hand in ``build-packages``
or ``stage-packages``.


ROS 2 extensions
~~~~~~~~~~~~~~~~

Three new extensions — :ref:`ros2-humble <reference-ros2-humble>`,
:ref:`ros2-jazzy <reference-ros2-jazzy>`, and
:ref:`ros2-lyrical <reference-ros2-lyrical>` — reduce the boilerplate required
to build ROS 2 rocks. Each extension targets one ROS 2 distribution and
automatically adds the ROS 2 apt repository and injects ``ROS_DISTRO`` into the
build environment.


Contributors
------------

We would like to express a big thank you to all the people who contributed to this release.

:literalref:`@artivis <https://github.com/artivis>`.
