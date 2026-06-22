.. meta::
    :description: Reference documentation for the ros2-lyrical extension, which configures a Rockcraft project to build ROS 2 Lyrical packages for ubuntu@26.04.

.. _reference-ros2-lyrical:

ros2-lyrical extension
======================

The ``ros2-lyrical`` extension streamlines the process of building
`ROS 2 Lyrical Lizard <https://docs.ros.org/>`_ rocks targeting
the ``ubuntu@26.04`` base.

It automatically:

* Adds the `ROS 2 apt repository <http://packages.ros.org/ros2/ubuntu>`_ for
  the ``resolute`` suite to ``package-repositories``.
* Injects ``ROS_DISTRO: lyrical`` into the ``build-environment`` of every part,
  so the :ref:`colcon plugin <rockcraft_colcon_plugin>` can source the correct
  underlay workspace.

.. note::

    The ``ros2-lyrical`` extension is compatible with the ``ubuntu@26.04`` base
    only. Use :ref:`ros2-humble <reference-ros2-humble>` for ``ubuntu@22.04`` or
    :ref:`ros2-jazzy <reference-ros2-jazzy>` for ``ubuntu@24.04``.

.. important::

    This extension is **experimental**: its behaviour may change in future
    releases. Set ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=true`` in your
    environment to enable it.


Usage
-----

Add ``ros2-lyrical`` to the ``extensions`` list of your project file:

.. code-block:: yaml
    :caption: rockcraft.yaml

    name: my-ros2-lyrical-rock
    base: ubuntu@26.04
    version: "0.1"
    summary: My ROS 2 Lyrical rock
    description: A rock built with the ros2-lyrical extension.
    license: Apache-2.0
    platforms:
      amd64:

    extensions: [ros2-lyrical]

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
        suites: [resolute]
        key-id: C1CF6E31E6BADE8868B172B4F42ED6FBAB17C654

    parts:
      my-node:
        build-environment:
          - ROS_DISTRO: lyrical


Useful links
------------

* :ref:`rockcraft_colcon_plugin` — the plugin used to build ROS 2 packages
* `ROS 2 apt repository <http://packages.ros.org>`_
