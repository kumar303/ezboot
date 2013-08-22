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

Do you really need this? Probably not!
``ezboot`` is intended for B2G platform developers.
If you are a B2G **app** developer you should try the
`Firefox OS Simulator`_ first because that will have
better features for you (such as Push To Device).

Requirements:

* Mac or Linux.

  * On Mac you might need to install XCode with Command Line Tools
    from https://developer.apple.com/downloads/
  * Windows could be supported but prepare to send patches.

* You *must* use a build of B2G that has Marionette enabled.
  More details below.
* Python 2.7 or greater (Python 3 isn't suported yet)
* The `pip`_ command to install Python packages

  * The best way to set up Python and `pip`_ on Mac is to use
    `homebrew`_. Once homebrew is installed type
    ``brew install python``. This will give you the ``pip`` command.

* ``adb`` needs to be on your ``$PATH``.
  Get it from the `Android SDK`_.
* Some additional Python modules will be installed as dependencies

Caveats:

* You should not enable the Remote Debugging setting on B2G when
  Marionette is enabled. This will create conflicting debugger listeners.
  See https://bugzilla.mozilla.org/show_bug.cgi?id=764913 for info.

.. _`Android SDK`: http://developer.android.com/sdk/index.html
.. _`Firefox OS Simulator`: https://developer.mozilla.org/en-US/docs/Mozilla/Firefox_OS/Using_Firefox_OS_Simulator
.. _`homebrew`: http://mxcl.github.com/homebrew/

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

First Timers
------------

You'll try anything at least once, right? The very *first* time you run
``ezboot flash`` you probably need to enable Remote Debugging first by
digging into
Settings > Device Information > More Information > Developer.
Otherwise, ``adb`` won't be able to connect.
This only applies if you had flashed with a B2G build that did not have
Marionette enabled.
If you've never installed B2G at all then you need to enable debugger
connections on Android.

Usage
=====

Run this for a quick reference::

    ezboot --help

Using Ezboot To Work With Marketplace Payments
----------------------------------------------

To whet your appetite, here is a full example of ezboot's intended use.
This `documentation <https://webpay.readthedocs.org/en/latest/use_hosted_webpay.html#set-up-a-device-with-ezboot>`_
shows you how to make a local config file and use ezboot to quickly prepare a B2G
device for hacking on the Firefox Marketplace payments system.

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

Using a config file greatly simplifies ezboot because you won't have to set
commonly used option values.

Commands
========

desktop
-------

This downloads a fresh desktop B2G build and installs it for use.
Here is a full reference::

    ezboot desktop --help

With the default args it will grab the latest B2G18 build.
If you need to install a different build just set the platform
specific URL. For example, if you are on a Mac and you want to get 1.0.1,
set this::

    ezboot desktop --mac64-url http://ftp.mozilla.org/pub/mozilla.org/b2g/nightly/latest-mozilla-b2g18_v1_0_1/b2g-18.0.multi.mac64.dmg

dl
--

This downloads a device build and saves the Zip file to a custom directory.
The build will not be flashed to a
device and any subsequent ``reflash`` command will not attempt to use
it. This is just a convenient way to grab a build without logging in;
the same user/pass options from ``flash`` apply here.

Here is a full reference::

    ezboot dl --help

You can set a custom location with ``ezboot dl --location=...``.
By default it will save builds to ``~/Downloads``.

flash
-----

This downloads a device build and flashes it to your device.
Here is a full reference::

    ezboot flash --help

You will have to specify which device you want to flash since every device has
a separate build that must be used to flash it. You can do that like so::

    ezboot flash --flash_device unagi

or, if you have the URL of your build, then do it like so::

    ezboot flash --flash_url http://pvtbuilds.mozilla.org/...

You can also set these in your ``ezboot.ini`` config file::

    [flash]
    flash_device = unagi/inari

or::

    [flash]
    flash_url = http://pvtbuilds.mozilla.org/...

Note, that if you set both ``flash_url`` and ``flash_device``, the value
provided for ``flash_url`` will override the default URL for the device
value you have provided. Please refer to the full reference.

Rest of the defaults will probably work for you. If you don't want
to be prompted for your username/password each time, you can save
them in an ``ezboot.ini`` config file::

    [flash]
    flash_user = the_user
    flash_pass = secret$password

Captain Obvious says don't commit your password to a public repo.

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

install
-------

Install an app from the Firefox Marketplace.

::

    ezboot install --help

This is an alternative to specifying manifest URLs in ``setup`` and will let
you install an app by name. Example::

    ezboot install --app 'Sliding Puzzle' --browser

install_mkt
-----------

Install a pre-production version of the `packaged Marketplace`_ app.
This requires you to run ``mkt_certs`` first.

::

    ezboot install_mkt --help

Example::

    ezboot install_mkt --dev

Because some bootstrapping is necessary this will install the app from your
B2G browser.

.. _`packaged Marketplace`: https://github.com/mozilla/fireplace

kill
----

This kills all running apps which may be useful when you need to reload
styles, js or other assets.

::

    ezboot kill --help

The ``recss`` command might be faster.

login
-----

Make sure a `Persona`_ screen is open on the device then type
``ezboot login``. Here is a reference::

    ezboot login --help

This lets you type the username / password to a new Persona account from
your nice desktop keyboard instead of the device keypad. In a real world
situation this wouldn't be as annoying since Persona remembers who you are
but for development you'll be typing new accounts all the time for testing.

.. _Persona: https://login.persona.org/

mkt_certs
---------

This pushes the cert files to your device so that you can install the
Marketplace packaged app (dev version) with elevated privileges and install
signed apps from that Marketplace. You obviously don't need this if you simply
want to use the production version of Marketplace that is pre-installed on
device.

::

    ezboot mkt_certs --help

Ask someone for a cert file
(see `this issue <https://github.com/briansmith/marketplace-certs/issues/1>`_),
download it, and unzip it.
You can install certs for the Marketplace dev packaged app like this::

   ezboot mkt_certs --dev --certs_path ~/Downloads/certdb.tmp/

reflash
-------

This flashes the last downloaded build without downloading a new one.
This is an easy way to clear cookies and other saved artifacts on device.

::

    ezboot reflash --help

See the ``flash`` command for more info.

recss
-----

This reloads all stylesheets on the current frame. More info::

    ezboot recss --help

setup
-----

This sets up your flashed device for usage. Here is the full reference::

    ezboot setup --help

It can do the following:

* configure WiFi
* pre-install some apps
* put custom prefs on the device

The ``--apps`` argument takes multiple values. In a config file, add them
one per line in an ``ezboot.ini`` config file like this::

    [setup]
    apps = https://marketplace-dev.allizom.org/manifest.webapp
           https://marketplace.allizom.org/manifest.webapp
    wifi_ssid = ...
    wifi_key = WPA-PSK
    wifi_pass = ...

By convention, if you put a custom prefs file in ``./ezboot/custom-prefs.js``
where dot is the working directory then it will be pushed to
``/data/local/user.js`` on the device. Any existing custom prefs are not
preserved.

Why?
====

While automated functional tests are fantastic I also want to make sure
developers are testing their changes manually on real devices with the
latest builds. It's a pain to maintain a development device yourself
so this created an itch that had to be scratched.
There is plenty of prior art on B2G scripts but each had different goals or
they were done with cryptic bash magic.
