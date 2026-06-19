.. meta::
    :description: Reference documentation for the ros2-jazzy extension, which configures a Rockcraft project to build ROS 2 Jazzy packages for ubuntu@24.04.

.. _reference-ros2-jazzy:

ros2-jazzy extension
====================

The ``ros2-jazzy`` extension streamlines the process of building
`ROS 2 Jazzy Jalisco <https://docs.ros.org/en/jazzy/>`_ rocks targeting
the ``ubuntu@24.04`` base.

It automatically:

* Adds the `ROS 2 apt repository <http://packages.ros.org/ros2/ubuntu>`_ for
  the ``noble`` suite to ``package-repositories``.
* Injects ``ROS_DISTRO: jazzy`` into the ``build-environment`` of every part,
  so the :ref:`colcon plugin <rockcraft_colcon_plugin>` can source the correct
  underlay workspace.

.. note::

    The ``ros2-jazzy`` extension is compatible with the ``ubuntu@24.04`` base
    only. Use :ref:`ros2-humble <reference-ros2-humble>` for ``ubuntu@22.04`` or
    :ref:`ros2-lyrical <reference-ros2-lyrical>` for ``ubuntu@26.04``.

.. important::

    This extension is **experimental**: its behaviour may change in future
    releases. Set ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` in your
    environment to enable it.


Usage
-----

Add ``ros2-jazzy`` to the ``extensions`` list of your project file:

.. code-block:: yaml
    :caption: rockcraft.yaml

    name: my-ros2-jazzy-rock
    base: ubuntu@24.04
    version: "0.1"
    summary: My ROS 2 Jazzy rock
    description: A rock built with the ros2-jazzy extension.
    license: Apache-2.0
    platforms:
      amd64:

    extensions: [ros2-jazzy]

    parts:
      my-node:
        plugin: colcon
        source: .

The extension adds the following to the above project file at build time:

.. code-block:: yaml

    package-repositories:
      - type: apt
        url: http://packages.ros.org/ros2/ubuntu
        components: [main]
        suites: [noble]
        key-id: C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654

    parts:
      my-node:
        build-environment:
          - ROS_DISTRO: jazzy


Useful links
------------

* :ref:`rockcraft_colcon_plugin` — the plugin used to build ROS 2 packages
* `ROS 2 Jazzy documentation <https://docs.ros.org/en/jazzy/>`_
* `ROS 2 apt repository <http://packages.ros.org>`_
