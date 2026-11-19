.. meta::
    :description: Reference documentation for the ros2-lyrical extension, which configures a Rockcraft project to build ROS 2 Lyrical packages for ubuntu@26.04.

.. _reference-ros2-lyrical:

ROS 2 Lyrical
=============

The ROS 2 Lyrical extension streamlines the process of building
`ROS 2 Lyrical Luth <https://docs.ros.org/>`_ application rocks.

The extension adds the `ROS 2 apt repository
<http://packages.ros.org/ros2/ubuntu>`_ for the ``resolute`` suite, sets
``ROS_DISTRO: lyrical`` in the build environment of every part so that the
:ref:`colcon plugin <rockcraft_colcon_plugin>` can find the underlay workspace,
and adds launcher scripts that source the ROS 2 environment at runtime.

.. note::
    The ROS 2 Lyrical extension is compatible with the ``bare`` and
    ``ubuntu@26.04`` bases. Use :ref:`ROS 2 Foxy <reference-ros2-foxy>` for
    ``ubuntu@20.04``, :ref:`ROS 2 Humble <reference-ros2-humble>` for
    ``ubuntu@22.04`` or :ref:`ROS 2 Jazzy <reference-ros2-jazzy>` for
    ``ubuntu@24.04``.

    The extension is experimental. Set
    ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=1`` when running Rockcraft to use
    it.

Use the extension
-----------------

Declare the extension in ``rockcraft.yaml``:

.. code-block:: yaml
   :caption: rockcraft.yaml

   extensions:
     - ros2-lyrical

To inspect the parts, services, and other configuration contributed by the
extension, run ``rockcraft expand-extensions`` in the same directory as the
``rockcraft.yaml`` file.

.. _reference-ros2-lyrical-project-requirements:

Project requirements
--------------------

To use the ``ros2-lyrical`` extension, the project must contain a colcon
workspace: one or more ROS 2 packages, each with a ``package.xml`` file, built
by a part that uses the :ref:`colcon plugin <rockcraft_colcon_plugin>`.

For rocks with ``base: bare``:

- ``build-base`` is mandatory and must be ``ubuntu@26.04``, so that the ROS 2
  apt repository (``resolute`` suite) matches the build environment. Rockcraft
  rejects any other ``build-base``.
- The rock needs a shell and the basic utilities, because the launcher scripts
  run with ``/bin/sh`` and some ROS 2 Python executables use
  ``#!/usr/bin/env python3``. Stage the ``base-files``, ``coreutils`` and
  ``dash`` packages.

For example:

.. code-block:: yaml
   :caption: rockcraft.yaml

   base: bare
   build-base: ubuntu@26.04

   parts:
     my-node:
       plugin: colcon
       source: .
       stage-packages:
         - base-files
         - coreutils
         - dash

.. _reference-ros2-lyrical-launchers:

Run the application
-------------------

The extension adds a part named ``ros2-lyrical.launch`` that installs two
scripts in the rock. Both source the ROS 2 underlay in ``/opt/ros/lyrical`` and
then the workspace overlay in ``/opt/ros/overlay``, before running the command:

- ``/usr/bin/ros2`` runs the ``ros2`` command-line tool, for example
  ``ros2 run <package> <executable>``.
- ``/usr/bin/ros2-source`` runs any other command, for executables that aren't
  ``ros2`` invocations.

Service and entrypoint commands must use one of them, because the ROS 2
libraries aren't in the default library search path.

The ``ros2`` tool also needs the package that provides the subcommand in the
rock, such as ``ros-lyrical-ros2run`` for ``ros2 run`` or
``ros-lyrical-ros2launch`` for ``ros2 launch``. For example, to list it in the
``stage-packages`` of your part:

.. code-block:: yaml
   :caption: rockcraft.yaml

   services:
     my-node:
       override: replace
       startup: enabled
       command: ros2 run my_package my_executable

   parts:
     my-node:
       plugin: colcon
       source: .
       stage-packages:
         - ros-lyrical-ros2run

Useful links
------------

* :ref:`rockcraft_colcon_plugin` — the plugin used to build ROS 2 packages
* `ROS 2 Lyrical documentation <https://docs.ros.org/>`_
* `ROS 2 apt repository <http://packages.ros.org>`_
