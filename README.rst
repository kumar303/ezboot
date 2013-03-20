======
ezboot
======

Automatically configure a `Boot2Gecko`_ Device. It's so ez!

.. _`Boot2Gecko`: https://developer.mozilla.org/en-US/docs/Mozilla/Firefox_OS

This is a command line script for the convenience of
developing on B2G such that you need to flash new builds
to your device periodically and begin hacking ASAP.

Features:

* Automatically downloads the latest build and flashes it
* Configures WiFi on your device
* Pre-installs apps that you commonly need
* Puts custom prefs on your device
* Easy, intuitive command line
* You can use a config file for everything
* Frictionless convention over configuration

Do you really need this? Probably not! You should try the
`Firefox OS Simulator`_ first. There are some device
interaction features coming very soon to the simulator
(such as Push To Device)
that will hopefully make this script obsolete.

Requirements:

* Mac or Linux.

  * On Mac you might need to install XCode with Command Line Tools
    from https://developer.apple.com/downloads/
  * Windows could be supported but prepare to send patches.

* You *must* use a build of B2G that has Marionette enabled.
  More details below.
* Python 2.7 or greater (Python 3 isn't suported yet)
* ``adb`` needs to be on your ``$PATH``.
  Get it from the `Android SDK`_.
* Some additional Python modules will be installed as dependencies

Caveats:

* You should not enable the Remote Debugging setting on B2G when
  Marionette is enabled. This will create conflicting debugger listeners.
  See https://bugzilla.mozilla.org/show_bug.cgi?id=764913 for info.

.. _`Android SDK`: http://developer.android.com/sdk/index.html
.. _`Firefox OS Simulator`: https://developer.mozilla.org/en-US/docs/Mozilla/Firefox_OS/Using_Firefox_OS_Simulator

Contents:

.. contents::
      :local:

Install
=======

With `pip`_, run this::

    pip install ezboot

This pulls in some dependencies so you may want to use a common
`virtualenv`_ and adjust your ``$PATH`` so you can use ``ezboot`` for
any project, e.g. ``/path/to/.virtualenvs/ezboot/bin``.

To install from source::

   git clone git://github.com/kumar303/ezboot.git
   cd ezboot
   python setup.py develop

.. _`pip`: http://www.pip-installer.org/en/latest/
.. _`virtualenv`: http://pypi.python.org/pypi/virtualenv

Source
------

The source is available at https://github.com/kumar303/ezboot/

Marionette
----------

For this script to work you *must* flash your device with a B2G build that
has `Marionette`_ enabled. The flash command will do
that for you. `Read this`_ if you want to build various flavors of
B2G with Marionette support yourself.

.. _`Marionette`: https://developer.mozilla.org/en-US/docs/Marionette
.. _`Read this`: https://developer.mozilla.org/en-US/docs/Marionette/Setup

Usage
=====

Run this for a quick reference::

    ezboot --help

Config file
-----------

You can set defaults for all argument values by creating an
``ezboot.ini`` file in the working directory. Make a section
for each sub command with long argument names as keys.
For example::

    [setup]
    wifi_ssid = mywifi
    wifi_key = WPA-PSK
    wifi_pass = my secure password with spaces
    apps = https://marketplace-dev.allizom.org/manifest.webapp
           https://marketplace.allizom.org/manifest.webapp

    [flash]
    flash_user = ...
    flash_pass = ...

Commands
========

flash
-----

This downloads a build and flashes it to your device.
Here is a full reference::

    ezboot flash --help

The defaults will probably do what you want. If you don't want
to be prompted for your username/password each time, you can save
them in an ``ezboot.ini`` config file::

    [flash]
    flash_user = the_user
    flash_pass = secret$password

Captain Obvious says don't commit your password to a public repo.

setup
-----

This sets up your flashed device for usage. Here is the full reference::

    ezboot setup --help

It does all this when the corresponding options have values:

* configures WiFi
* pre-installs some apps
* puts custom prefs on the device

The ``--apps`` argument takes multiple values. In a config file, add them
one per line in an ``ezboot.ini`` config file like this::

    [setup]
    apps = https://marketplace-dev.allizom.org/manifest.webapp
           https://marketplace.allizom.org/manifest.webapp
    wifi_ssid = ...
    wifi_key = WPA-PSK
    wifi_pass = ...

By convention, if you put a config file in ``./ezboot/custom-prefs.js``
where dot is the working directory then it will be pushed to
``/data/local/user.js`` on the device.

http
----

This restarts your phone with HTTP logging *temporarily* enabled.
Here is the full reference::

    ezboot http --help

This runs B2G on the device until you interrupt it (^C). After you're
finished the console will tell you where to find a log of all HTTP
requests/responses. When you view the file it might warn you that it
has binary content but that's typically just at the beginning of the file.
Keep paging.

Why?
====

While automated functional tests are fantastic I also want to make sure
developers are testing their changes manually on real devices with the
latest builds. It's a pain to maintain a development device yourself
so this created an itch that had to be scratched.
There is some prior art on B2G scripts but they had different goals or
they were done with cryptic bash magic.
