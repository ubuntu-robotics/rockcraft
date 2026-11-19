.. meta::
    :description: The reference documentation for all extensions in Rockcraft.

.. _reference-extensions:

Extensions
==========

Extensions are reusable configuration fragments that simplify a
``rockcraft.yaml`` file for common application frameworks. An extension
configures the parts, services, and other keys needed to build and run the
application, while still allowing you to customize the generated
configuration in the project file.

The top-level ``extensions`` key in ``rockcraft.yaml`` defines the extension
used by the project. When Rockcraft loads the project, it expands the extension
and combines its configuration with your project file.

.. _reference-extensions-ubuntu-2604-frameworks:

Ubuntu 26.04 LTS framework extensions
-------------------------------------

The Flask, Django, FastAPI, Go, and Express framework extensions are stable on their
supported bases earlier than Ubuntu 26.04 LTS. The Spring Boot extension remains
experimental on its supported bases, and the Ubuntu 26.04 LTS implementations of all
six extensions are experimental. To use one of these extensions with Ubuntu 26.04 LTS,
set ``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=1`` when running Rockcraft.

Rockcraft selects the extension implementation from ``build-base`` when it is set, or from ``base`` otherwise. For a rock with ``base: bare``, ``build-base`` is mandatory. For example,
``base: bare`` with ``build-base: ubuntu@24.04`` uses the stable extension
implementation and doesn't require the experimental extensions environment
variable. For migration guidance, see
:ref:`how-to-migrate-2604`.

On Ubuntu 26.04 LTS, these six extensions place application content under
``/app`` and create ``/app-data`` for application-generated data.
``/app-data`` is owned by ``_daemon_`` and is writable by the application
service. Use it as the persistent-at-runtime application data directory,
rather than for the application content installed under ``/app``.

``/app-data`` is part of the image's container filesystem. Its contents don't
persist across container replacement unless a volume is mounted at that path.

.. toctree::
    :maxdepth: 1

    flask-framework
    django-framework
    fastapi-framework
    go-framework
    express-framework
    spring-boot-framework
    ros2-foxy
    ros2-humble
    ros2-jazzy
    ros2-lyrical

.. _reference-extensions-ros2:

ROS 2 extensions
----------------

The ROS 2 extensions build ROS 2 workspaces with the
:ref:`colcon plugin <rockcraft_colcon_plugin>`. Each extension targets one ROS 2
distribution and its matching Ubuntu base:

.. list-table::
    :header-rows: 1

    * - Extension
      - ROS 2 distribution
      - Base
    * - :ref:`ros2-foxy <reference-ros2-foxy>`
      - Foxy Fitzroy
      - ``ubuntu@20.04``
    * - :ref:`ros2-humble <reference-ros2-humble>`
      - Humble Hawksbill
      - ``ubuntu@22.04``
    * - :ref:`ros2-jazzy <reference-ros2-jazzy>`
      - Jazzy Jalisco
      - ``ubuntu@24.04``
    * - :ref:`ros2-lyrical <reference-ros2-lyrical>`
      - Lyrical Luth
      - ``ubuntu@26.04``

All of them:

- Add the ROS 2 apt repository for the suite of the base.
- Set ``ROS_DISTRO`` in the build environment of every part.
- Add a launcher part that provides the ``ros2`` and ``ros2-source`` wrappers.

The ROS 2 extensions are experimental on every base. Set
``ROCKCRAFT_ENABLE_EXPERIMENTAL_EXTENSIONS=1`` when running Rockcraft to use
them.
