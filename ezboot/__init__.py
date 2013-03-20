#!/usr/bin/env python
"""
Automatically configure a Boot2Gecko Device. It's so ez!

You can set defaults for argument values by creating an
ezboot.ini file in the working directory. Make a section
for each sub command like this with long argument values.
For example:

    [setup]
    wifi_ssid = mywifi
    wifi_pass = my secure password with spaces

    [flash]
    flash_url = ...

"""
import argparse
import ConfigParser
from getpass import getpass
import os
import socket
import shutil
import subprocess
from subprocess import check_call
import sys
import tempfile
import time

from gaiatest import GaiaDevice, GaiaApps, GaiaData, LockScreen
from marionette import Marionette, MarionetteTouchMixin
from marionette.errors import NoSuchElementException
from marionette.errors import TimeoutException
import requests
from requests.auth import HTTPBasicAuth


def sh(cmd):
    return check_call(cmd, shell=True)


def wait_for_element_displayed(mc, by, locator, timeout=8):
    timeout = float(timeout) + time.time()

    while time.time() < timeout:
        time.sleep(0.5)
        try:
            if mc.find_element(by, locator).is_displayed():
                break
        except NoSuchElementException:
            pass
    else:
        raise TimeoutException(
            'Element %s not visible before timeout' % locator)


def get_installed(apps):
    apps.marionette.switch_to_frame()
    res = apps.marionette.execute_async_script("""
        var req = navigator.mozApps.getInstalled();
        req.onsuccess = function _getInstalledSuccess() {
            var apps = [];
            for (var i=0; i < req.result.length; i++) {
                var ob = req.result[i];
                var app = {};
                // Make app objects JSONifiable.
                for (var k in ob) {
                    app[k] = ob[k];
                }
                apps.push(app);
            }
            marionetteScriptFinished(apps);
        };
        """)
    return res


def set_up_device(args):
    mc = Marionette('localhost', args.adb_port)
    for i in range(3):
        try:
            mc.start_session()
            break
        except socket.error:
            sh('adb forward tcp:%s tcp:%s' % (args.adb_port, args.adb_port))

    # Look away! This is how gaiatest did it. *shrug*
    mc.__class__ = type('Marionette', (Marionette, MarionetteTouchMixin), {})
    device = GaiaDevice(mc)

    device.restart_b2g()

    apps = GaiaApps(mc)
    data_layer = GaiaData(mc)
    lockscreen = LockScreen(mc)
    mc.setup_touch()

    lockscreen.unlock()
    apps.kill_all()

    if args.wifi_ssid:
        print 'Configuring WiFi'
        assert args.wifi_key and args.wifi_pass, (
            'Missing --wifi_key and --wifi_pass options')
        args.wifi_key = args.wifi_key.upper()

        data_layer.enable_wifi()
        if args.wifi_key == 'WPA-PSK':
            pass_key = 'psk'
        elif args.wifi_key == 'WEP':
            pass_key = 'wep'
        else:
            assert 0, 'not sure what key to use for %r' % args.wifi_key

        data = {'ssid': args.wifi_ssid, 'keyManagement': args.wifi_key,
                pass_key: args.wifi_pass}
        data_layer.connect_to_wifi(data)

    print 'Installing these apps: %s' % (args.apps or None)
    for manifest in args.apps:
        # There is probably a way easier way to do this by adb pushing
        # something. Send me a patch!
        mc.switch_to_frame()
        try:
            data = requests.get(manifest).json()
        except Exception, exc:
            print ' ** mainfest %s failed' % manifest
            print ' ** requests error: %s: %s' % (exc.__class__.__name__,
                                                  exc)
            continue
        app_name = data['name']
        all_apps = set(a['manifest']['name'] for a in get_installed(apps))
        if app_name not in all_apps:
            mc.execute_script('navigator.mozApps.install("%s");' % manifest)
            wait_for_element_displayed(mc, 'id', 'app-install-install-button')
            yes = mc.find_element('id', 'app-install-install-button')
            mc.tap(yes)
            wait_for_element_displayed(mc, 'id', 'system-banner')

    if args.custom_prefs and os.path.exists(args.custom_prefs):
        print 'Pushing payment prefs from %s' % args.custom_prefs
        sh('adb shell stop b2g')
        try:
            sh('adb push "%s" /data/local/user.js' % args.custom_prefs)
        finally:
            sh('adb shell start b2g')

    print 'Your device is rebooting'


def http_log_restart(args):
    sh('adb shell stop b2g')
    print "restarting with HTTP logging enabled"
    print "press control+C to quit"
    sh('adb shell rm /data/local/tmp/http.log')
    p = subprocess.Popen("""adb shell <<SHELL
#export NSPR_LOG_MODULES=timestamp,nsHttp:5,nsSocketTransport:5,nsHostResolver:5
export NSPR_LOG_MODULES=nsHttp:3
export NSPR_LOG_FILE=/data/local/tmp/http.log
/system/bin/b2g.sh

SHELL
        """, shell=True)
    try:
        print 'Get output with adb logcat'
        p.wait()
    except KeyboardInterrupt:
        p.kill()
        p.wait()

    tmp = tempfile.gettempdir()
    os.chdir(tmp)
    sh('adb pull /data/local/tmp/http.log')
    print '*' * 80
    print 'Log file: %s/http.log' % tmp
    print '*' * 80
    sh('adb reboot')


def flash_device(args):
    print 'Downloading %s' % args.flash_url

    user = args.flash_user
    password = args.flash_pass
    if not user or not password:
        done = False
        while not done:
            user = raw_input('LDAP username: ')
            password = getpass('password: ')
            if raw_input('OK? y/n ').strip().startswith('y'):
                done = True

    dest = tempfile.mkdtemp(prefix='ezboot_')
    wd = os.getcwd()
    try:
        os.chdir(dest)
        print 'In %s' % dest
        zn = os.path.basename(args.flash_url)
        res = requests.get(args.flash_url,
                           auth=HTTPBasicAuth(user, password), stream=True)
        zipdest = open(os.path.basename(args.flash_url), 'wb')
        print 'Saving %s' % zipdest.name
        dots = 1
        dir = ['.', ' ']
        for chunk in res.iter_content(chunk_size=1024 * 13):
            zipdest.write(chunk)
            sys.stdout.write("\r%s%s" % (dir[0] * dots,
                                         dir[1] * (80 - dots)))
            sys.stdout.flush()
            dots += 1
            if dots >= 80:
                dots = 1
                dir.reverse()
        print
        res.close()
        zipdest.close()

        sh('unzip %s' % zipdest.name)
        os.chdir('b2g-distro')
        sh('./flash.sh')

    finally:
        shutil.rmtree(dest)
        os.chdir(wd)


def find_executable(name):
    """
    Finds the actual path to a named command.

    The first one on $PATH wins.
    """
    for pt in os.environ.get('PATH', '').split(':'):
        candidate = os.path.join(pt, name)
        if os.path.exists(candidate):
            return candidate


class Formatter(argparse.RawDescriptionHelpFormatter,
                argparse.ArgumentDefaultsHelpFormatter):
    pass


def main():
    conf_parser = argparse.ArgumentParser(add_help=False)
    conf_parser.add_argument('-c', '--config',
                             default=os.path.join(os.getcwd(), 'ezboot.ini'),
                             help='Set argument defaults from config file')

    args, remaining_argv = conf_parser.parse_known_args()

    config = None
    if args.config and os.path.exists(args.config):
        config = ConfigParser.SafeConfigParser()
        config.read([args.config])

    cmd = argparse.ArgumentParser(description=__doc__,
                                  parents=[conf_parser],
                                  formatter_class=Formatter)

    sub = cmd.add_subparsers(help='sub-command help')

    def sub_parser(action, help='', **kw):
        if config:
            # The config file can list options for each sub command
            # but if two commands have the same option name only one will win.
            try:
                cfg = dict(config.items(action))
                for key, val in cfg.items():
                    if '\n' in val:
                        # Turn a multi-line value into a list.
                        cfg[key] = [a for a in val.strip().split('\n')]
                cmd.set_defaults(**cfg)
            except ConfigParser.NoSectionError:
                pass
        kw['formatter_class'] = Formatter
        return sub.add_parser(action, help=help, description=help, **kw)

    flash = sub_parser('flash', help='Download a build and flash it')
    u = ('https://pvtbuilds.mozilla.org/pub/mozilla.org/b2g/nightly/'
         'mozilla-b2g18-unagi-eng/latest/unagi.zip')
    flash.add_argument('--flash_url', default=u,
                       help='URL of B2G build to flash. '
                            'This requires a username/password.')
    flash.add_argument('--flash_user',
                       help='Username for build URL. It will prompt '
                            'when empty')
    flash.add_argument('--flash_pass',
                       help='Password for build URL. It will prompt when empty')
    flash.set_defaults(func=flash_device)

    setup = sub_parser('setup', help='Set up a flashed device for usage')
    setup.add_argument('--adb_port', default=2828, type=int,
                       help='adb port to forward on the device.')
    setup.add_argument('--wifi_ssid', help='WiFi SSID to connect to')
    setup.add_argument('--wifi_key', choices=['WPA-PSK', 'WEP'],
                       help='WiFi key management.')
    setup.add_argument('--wifi_pass', help='WiFi password')
    setup.add_argument('--apps', nargs='*', metavar='MANIFEST_URL',
                       help='App manifest URLs to install on the device '
                            'at boot.')
    setup.add_argument('--custom_prefs', metavar='JS_FILE',
                       default=os.path.join(os.getcwd(), 'ezboot',
                                            'custom-prefs.js'),
                       help='Custom JS prefs file to copy into '
                            '/data/local/user.js. Exising user.js is '
                            'not preserved.')
    setup.set_defaults(func=set_up_device)

    http = sub_parser('http',
                      help='Restart the device with HTTP logging '
                           'enabled. This assumes you previously '
                           'set up the device.')
    http.set_defaults(func=http_log_restart)

    args = cmd.parse_args(remaining_argv)

    if config:
        print 'Using config: %s' % args.config
    if not find_executable('adb'):
        cmd.error("""adb not found on $PATH

You can get it from the Android SDK at:
http://developer.android.com/sdk/index.html
""")

    # Hmm. This is tricky. The config file won't give us a list
    # if there is only one item.
    if args.apps and isinstance(args.apps, basestring):
        args.apps = [args.apps]

    args.func(args)


if __name__ == '__main__':
    main()
