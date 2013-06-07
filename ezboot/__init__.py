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
from contextlib import contextmanager
from getpass import getpass
import os
import socket
import shutil
import subprocess
from subprocess import check_call
import sys
import time
import traceback
import xml.etree.ElementTree as ET

from gaiatest import GaiaDevice, GaiaApps, GaiaData, LockScreen
from marionette import Marionette, MarionetteTouchMixin
from marionette.errors import NoSuchElementException
from marionette.errors import TimeoutException
import requests
from requests.auth import HTTPBasicAuth

CHUNK_SIZE = 1024 * 13


def user_agrees(prompt='OK? Y/N [%s]: ', default='Y',
                strip_value=True, lower_value=True):
    val = raw_input(prompt % default)
    val = val.strip() if strip_value else val
    val = val.lower() if lower_value else val
    default = default.lower() if lower_value else default
    if val == default or val == '':
        return True

def sh(cmd):
    return check_call(cmd, shell=True)


def wait_for_element_displayed(mc, by, locator, timeout=10):
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


def wait_for_element_present(mc, by, locator, timeout=10):
    timeout = float(timeout) + time.time()

    while time.time() < timeout:
        time.sleep(0.5)
        try:
            return mc.find_element(by, locator)
        except NoSuchElementException:
            pass
    else:
        raise TimeoutException(
            'Element %s not found before timeout' % locator)


def wait_for_condition(mc, method, timeout=10,
                       message="Condition timed out"):
    """Calls the method provided with the driver as an argument until the
    return value is not False."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            value = method(mc)
            if value:
                return value
        except NoSuchElementException:
            pass
        time.sleep(0.5)
    else:
        raise TimeoutException(message)


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


class MarionetteWithTouch(Marionette, MarionetteTouchMixin):
    pass


def get_marionette(args):
    mc = MarionetteWithTouch('localhost', args.adb_port)
    for i in range(3):
        try:
            mc.start_session()
            break
        # Catching SystemExit because tracebacks are suppressed.
        # This won't be necessary after
        # https://bugzilla.mozilla.org/show_bug.cgi?id=863377
        except (socket.error, SystemExit):
            sh('adb forward tcp:%s tcp:%s' % (args.adb_port, args.adb_port))
    return mc


def set_up_device(args):
    mc = get_marionette(args)
    device = GaiaDevice(mc)
    try:
        device.restart_b2g()
    except Exception:
        print ' ** Check to make sure you don\'t have desktop B2G running'
        raise

    apps = GaiaApps(mc)
    data_layer = GaiaData(mc)
    lockscreen = LockScreen(mc)
    mc.setup_touch()

    lockscreen.unlock()
    apps.kill_all()

    if args.wifi_ssid:
        print 'Configuring WiFi'
        if not args.wifi_key or not args.wifi_pass:
            args.error('Missing --wifi_key or --wifi_pass option')
        args.wifi_key = args.wifi_key.upper()

        data_layer.enable_wifi()
        if args.wifi_key == 'WPA-PSK':
            pass_key = 'psk'
        elif args.wifi_key == 'WEP':
            pass_key = 'wep'
        else:
            args.error('not sure what key to use for %r' % args.wifi_key)

        data = {'ssid': args.wifi_ssid, 'keyManagement': args.wifi_key,
                pass_key: args.wifi_pass}
        data_layer.connect_to_wifi(data)

    for manifest in args.apps:
        # There is probably a way easier way to do this by adb pushing
        # something. Send me a patch!
        mc.switch_to_frame()
        try:
            data = requests.get(manifest).json()
            app_name = data['name']
            all_apps = set(a['manifest']['name'] for a in get_installed(apps))
            if app_name not in all_apps:
                print 'Installing %s from %s' % (app_name, manifest)
                mc.execute_script('navigator.mozApps.install("%s");' % manifest)
                wait_for_element_displayed(mc, 'id', 'app-install-install-button')
                yes = mc.find_element('id', 'app-install-install-button')
                mc.tap(yes)
                # This still works but the id check broke.
                # See https://bugzilla.mozilla.org/show_bug.cgi?id=853878
                wait_for_element_displayed(mc, 'id', 'system-banner')
        except Exception, exc:
            print ' ** installing manifest %s failed (maybe?)' % manifest
            print ' ** error: %s: %s' % (exc.__class__.__name__, exc)
            continue

    if args.custom_prefs and os.path.exists(args.custom_prefs):
        print 'Pushing custom prefs from %s' % args.custom_prefs
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
    device_log = '/data/local/ezboot-http.log'
    sh('adb shell rm %s' % device_log)
    p = subprocess.Popen("""adb shell <<SHELL
#export NSPR_LOG_MODULES=timestamp,nsHttp:5,nsSocketTransport:5,nsHostResolver:5
export NSPR_LOG_MODULES=nsHttp:3
export NSPR_LOG_FILE=%s
/system/bin/b2g.sh

SHELL
        """ % device_log,
        shell=True)
    try:
        print 'Get output with adb logcat'
        p.wait()
    except KeyboardInterrupt:
        try:
            p.kill()
            p.wait()
        except Exception, exc:
            print ' ** ignoring error: %s: %s' % (exc.__class__.__name__, exc)

    os.chdir(args.work_dir)
    sh('adb pull %s' % device_log)
    print '*' * 80
    print 'Log file: %s/%s' % (args.work_dir, os.path.basename(device_log))
    print '*' * 80
    sh('adb reboot')


def flash_device(args):
    default_build_urls = {
        'unagi': ('https://pvtbuilds.mozilla.org/pub/mozilla.org/b2g/nightly'
                  '/mozilla-b2g18_v1_0_1-unagi-eng/latest/unagi.zip'),
        'inari': ('https://pvtbuilds.mozilla.org/pvt/mozilla.org/b2gotoro'
                  '/nightly/mozilla-b2g18_v1_0_1-inari-eng/latest/inari.zip'),
    }

    if args.flash_device is None and args.flash_url is None:
        args.error('Try ezboot with flash with --flash_url or --flash_device '
                   'options. Or try ezboot flash --help for more details.')
    else:
        if args.flash_url:
            pass
        else:
            if args.flash_device.lower() in default_build_urls.keys():
                args.flash_url = default_build_urls[args.flash_device.lower()]
            else:
                prompt_msg = ('We don\'t have a URL to fetch latest build for '
                              'build for device "%s". Please provide a URL to '
                              'get a build for flashing your device: ' % args.flash_device)
                # ask for a URL because we don't have it
                args.flash_url = raw_input(prompt_msg)

    download_build(args)
    flash_last_dl(args)


def download_and_save_build(args):
    if not os.path.exists(args.location):
        print 'Creating download directory: %s' % args.location
        os.makedirs(args.location)
    zipdest = download_build(args, save_to=args.location, unzip=False)
    print 'Your build is available at %s' % zipdest


def download_build(args, save_to=None, unzip=True):
    print 'Downloading %s' % args.flash_url

    user = args.flash_user
    password = args.flash_pass
    if not user or not password:
        done = False
        while not done:
            user = raw_input('LDAP username: ')
            password = getpass('password: ')
            if user_agrees():
                done = True

    if save_to is None:
        dest = os.path.join(args.work_dir, 'last-build')
        if os.path.exists(dest):
            shutil.rmtree(dest)
        os.mkdir(dest)
    else:
        dest = save_to
    with pushd(dest):
        print 'In %s' % dest
        res = requests.get(args.flash_url,
                           auth=HTTPBasicAuth(user, password), stream=True)
        if res.status_code != 200:
            args.error('Got %s from %s (Is your password correct? '
                       'Is the URL correct?)' % (res.status_code,
                                                 args.flash_url))
        total_bytes = int(res.headers['content-length'])
        zipdest = open(os.path.basename(args.flash_url), 'wb')
        print 'Saving %s' % zipdest.name
        dots = 1
        chars = ['.', ' ']
        bytes_down = 0
        for chunk in res.iter_content(chunk_size=CHUNK_SIZE):
            bytes_down += CHUNK_SIZE
            zipdest.write(chunk)
            sys.stdout.write("\r%s%s %2.2f%%" % (chars[0] * dots,
                                         chars[1] * (80 - dots),
                                         100.0 * bytes_down / total_bytes))
            sys.stdout.flush()
            dots += 1
            if dots >= 80:
                dots = 1
                chars.reverse()
        print ''  # finish progress indicator
        res.close()
        zipdest.close()

        if unzip:
            sh('unzip %s' % zipdest.name)
        return os.path.abspath(zipdest.name)


def get_b2g_distro(args):
    dest = os.path.join(args.work_dir, 'last-build', 'b2g-distro')
    if not os.path.exists(dest):
        args.error('No build to flash. Did you run flash?')
    return dest


def flash_last_dl(args):
    dest = get_b2g_distro(args)
    show_build_info(args)
    with pushd(dest):
        sh('./flash.sh')


def kill_all_apps(args):
    mc = get_marionette(args)
    mc.setup_touch()
    apps = GaiaApps(mc)
    apps.kill_all()
    print 'Killed all apps'


def do_recss(args):
    mc = get_marionette(args)
    # From : http://david.dojotoolkit.org/recss.html
    js = """
function _doReCSS() {
    var i, a, s;
    a = document.getElementsByTagName('link');
    for (i = 0; i < a.length; i++) {
        s = a[i];
        if (s.rel.toLowerCase().indexOf('stylesheet') >= 0 && s.href) {
            var h = s.href.replace(/(&|\\?)forceReload=\\d+/, '');
            s.href = h + (h.indexOf('?') >= 0 ? '&' : '?') + 'forceReload=' + (new Date().valueOf())
        }
    }
};
_doReCSS();
    """
    mc.switch_to_frame()
    mc.execute_script(js)
    print 'Reset CSS'


def show_build_info(args):
    dest = get_b2g_distro(args)
    try:
        root = ET.parse(os.path.join(dest, 'sources.xml')).getroot()
        remotes = {}
        for rem in root.findall('./remote'):
            url = rem.attrib['fetch']
            if url.endswith('releases'):
                # Bah! The URL is wrong for web viewing.
                # Strip off the /releases
                parts = url.split('/')
                url = '/'.join(parts[:-1])
            remotes[rem.attrib['name']] = url

        print 'Build info:'
        for pj in ('gecko', 'gaia'):
            for el in root.findall("./project[@path='%s']" % pj):
                # E.G. https://git.mozilla.org/?p=releases/gaia.git
                #        ;a=commitdiff
                #        ;h=5a31a56b96a8fc559232d35dabf20411b9c2ca1d
                print '  %s/?p=releases/%s;a=commitdiff;h=%s' % (
                                remotes[el.attrib['remote']],
                                el.attrib['name'],
                                el.attrib['revision'])
    except Exception:
        traceback.print_exc()
        print ' ** could not get build info'


def do_login(args):
    mc = get_marionette(args)
    device = GaiaDevice(mc)
    apps = GaiaApps(mc)
    data_layer = GaiaData(mc)
    mc.setup_touch()

    _persona_frame_locator = ('css selector', "iframe")

    # Trusty UI on home screen
    _tui_container_locator = ('id', 'trustedui-frame-container')

    # Persona dialog
    _waiting_locator = ('css selector', 'body.waiting')
    _email_input_locator = ('id', 'authentication_email')
    _password_input_locator = ('id', 'authentication_password')
    _new_password = ('id', 'password')
    _verify_new_password = ('id', 'vpassword')
    _next_button_locator = ('css selector', 'button.start')
    _verify_start_button = ('css selector', 'button#verify_user')
    _returning_button_locator = ('css selector', 'button.returning')
    _sign_in_button_locator = ('id', 'signInButton')
    _this_session_only_button_locator = ('id', 'this_is_not_my_computer')

    # Switch to top level frame then Persona frame
    mc.switch_to_frame()
    wait_for_element_present(mc, *_tui_container_locator)
    trustyUI = mc.find_element(*_tui_container_locator)
    wait_for_condition(mc, lambda m: trustyUI.find_element(*_persona_frame_locator))
    personaDialog = trustyUI.find_element(*_persona_frame_locator)
    mc.switch_to_frame(personaDialog)

    try:
        ready = mc.find_element(*_email_input_locator).is_displayed()
    except NoSuchElementException:
        ready = False
    if not ready:
        print 'Persona email input is not present.'
        print 'Are you on a new login screen?'
        return

    done = False
    while not done:
        username = raw_input('Persona username: ')
        password = getpass('password: ')
        if user_agrees():
            done = True

    email_field = mc.find_element(*_email_input_locator)
    email_field.send_keys(username)

    #mc.tap(mc.find_element(*_next_button_locator)) #.click()
    mc.find_element(*_next_button_locator).click()

    try:
        wait_for_element_displayed(mc, *_new_password)
        # Creating a new account:
        password_field = mc.find_element(*_new_password)
        password_field.send_keys(password)
        v_password = mc.find_element(*_verify_new_password)
        v_password.send_keys(password)
        wait_for_element_displayed(mc, *_verify_start_button)
        mc.tap(mc.find_element(*_verify_start_button)) #.click()
    except TimeoutException:
        print 'Not a new account? Trying to log in to existing account'
        # Logging into an exisiting account:
        password_field = mc.find_element(*_password_input_locator)
        password_field.send_keys(password)
        wait_for_element_displayed(mc, *_returning_button_locator)
        mc.tap(mc.find_element(*_returning_button_locator)) #.click()

    print 'You should be logged in now'


@contextmanager
def pushd(newdir):
    wd = os.getcwd()
    try:
        os.chdir(newdir)
        yield
    finally:
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
    cmd.add_argument('--work_dir', default='~/.ezboot',
                     help='Working directory to save/delete temp data')
    cmd.add_argument('--adb_port', default=2828, type=int,
                     help='adb port to forward on the device. '
                          'Marionette will then connect to this port.')
    cmd.add_argument('--flash_url', default=None,
                     help='URL of B2G build to download. '
                          'This requires a username/password. '
                          'This overrides the URL to use if --flash_device is '
                          'also provided.')
    cmd.add_argument('--flash_user',
                     help='Username for build URL. It will prompt '
                          'when empty')
    cmd.add_argument('--flash_pass',
                     help='Password for build URL. It will prompt when '
                          'empty')
    cmd.add_argument('--flash_device', default=None,
                     help='The device you want to flash. Example: unagi')

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
    flash.set_defaults(func=flash_device)

    reflash = sub_parser('reflash', help='Re-flash the last build you '
                                         'downloaded')
    reflash.set_defaults(func=flash_last_dl)

    setup = sub_parser('setup', help='Set up a flashed device for usage')
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

    dl = sub_parser('dl', help='Download a build to a custom location')
    dl.add_argument('--location', help='Directory to download to',
                    default=os.path.expanduser('~/Downloads'))
    dl.set_defaults(func=download_and_save_build)

    http = sub_parser('http',
                      help='Restart the device with HTTP logging '
                           'enabled.')
    http.set_defaults(func=http_log_restart)

    info = sub_parser('info', help='Show info of last ezboot-downloaded '
                                   'build. This may not be exactly what is '
                                   'on your device.')
    info.set_defaults(func=show_build_info)

    login = sub_parser('login', help='Enter Persona login username/password. '
                                     'You must have a login prompt open '
                                     'on your device.')
    login.set_defaults(func=do_login)

    kill = sub_parser('kill',
                      help='Kill all running apps.')
    kill.set_defaults(func=kill_all_apps)

    recss = sub_parser('recss', help='Reload all stylesheets.')
    recss.set_defaults(func=do_recss)

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
    if hasattr(args, 'apps'):
        if args.apps and isinstance(args.apps, basestring):
            args.apps = [args.apps]
        if not args.apps:
            args.apps = []

    if hasattr(args, 'work_dir'):
        args.work_dir = os.path.expanduser(args.work_dir)
        if not os.path.exists(args.work_dir):
            os.mkdir(args.work_dir)

    # Make it easier for handlers to raise parser errors.
    args.error = cmd.error

    # This should cut down on any sad face errors that
    # might happen after, oh, say, downloading 180MB.
    print 'Waiting for your device (is it plugged in?)'
    sh('adb wait-for-device')
    print 'found it'

    args.func(args)


if __name__ == '__main__':
    main()
