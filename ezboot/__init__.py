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
import netifaces
import os
import pprint
import socket
import shutil
import subprocess
from subprocess import check_call, check_output
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET

from gaiatest import GaiaDevice, GaiaApps, GaiaData, LockScreen
from gaiatest.apps.browser.app import Browser
from gaiatest.apps.marketplace.app import Marketplace
from marionette import Marionette
from marionette.errors import NoSuchElementException, StaleElementException
from marionette.errors import TimeoutException
import requests
from requests.auth import HTTPBasicAuth

CHUNK_SIZE = 1024 * 13
TERM_WIDTH = 65  # number of terminal columns for progress indicator


def user_agrees(prompt='OK? Y/N [%s]: ', default='Y',
                strip_value=True, lower_value=True):
    val = raw_input(prompt % default)
    val = val.strip() if strip_value else val
    val = val.lower() if lower_value else val
    default = default.lower() if lower_value else default
    if val == default or val == '':
        return True


def select(choices, default=1, prompt='Please choose from the following [1]:'):
    """Create a prompt similar to select in bash."""

    invalid_choice = 'Not a valid choice. Try again.'

    for i, value in enumerate(choices):
        print '%s) %s' % (i+1, value[0])

    def get_choice():
        try:
            val = raw_input(prompt)
            if val == '':
                val = default
            val = int(val) - 1
        except ValueError:
            print invalid_choice
            return get_choice()
        except KeyboardInterrupt:
            print
            print "Bailing..."
            sys.exit(1)

        try:
            return choices[val]
        except IndexError:
            print invalid_choice
            return get_choice()

    return get_choice()


def sh(cmd):
    return check_call(cmd, shell=True)


def sh_output(cmd):
    return check_output(cmd, shell=True)


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


def wait_for_element_not_displayed(mc, by, locator, timeout=10):
    timeout = float(timeout) + time.time()

    while time.time() < timeout:
        time.sleep(0.5)
        try:
            if not mc.find_element(by, locator).is_displayed():
                break
        except StaleElementException:
            pass
        except NoSuchElementException:
            break
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


def get_marionette(args):
    mc = Marionette('localhost', args.adb_port)
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
    def install_apps():
        mc = get_marionette(args)
        device = GaiaDevice(mc)
        try:
            device.restart_b2g()
            print 'Your device is rebooting.'
        except Exception:
            print ' ** Check to make sure you don\'t have desktop B2G running'
            raise

        apps = GaiaApps(mc)
        apps.kill_all()

        lockscreen = LockScreen(mc)
        lockscreen.unlock()

        if args.wifi_ssid:
            print 'Configuring WiFi'
            if not args.wifi_key or not args.wifi_pass:
                args.error('Missing --wifi_key or --wifi_pass option')
            args.wifi_key = args.wifi_key.upper()

            data_layer = GaiaData(mc)
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

        # disconnect marionette client because install_app would need it
        mc.client.close()

        # install apps one by one
        for manifest in args.apps:
            args.manifest = manifest
            args.app = None
            install_app(args)

    def push_custom_prefs():
        print 'Pushing custom prefs from %s' % args.custom_prefs
        sh('adb shell stop b2g')
        try:
            sh('adb push "%s" /data/local/user.js' % args.custom_prefs)
        finally:
            sh('adb shell start b2g')
            print 'Your device is rebooting.'

    if args.apps is not None:
        install_apps()

    if args.custom_prefs and os.path.exists(args.custom_prefs):
        push_custom_prefs()


def get_ips_for_interface(interface):
    """Get the ips for a specific interface."""
    interface_ips = []
    try:
        for fam, data in netifaces.ifaddresses(interface).items():
            if fam == socket.AF_INET:
                for d in data:
                    ip = d.get('addr')
                    if ip and not ip.startswith('127'):
                        interface_ips.append((interface, ip))
        return interface_ips
    except ValueError, e:
        print >> sys.stderr, e
        print >> sys.stderr, 'You provided "%s". Choose one of:' % interface
        print >> sys.stderr, ', '.join(netifaces.interfaces())
        sys.exit(1)


def get_interface_data(interface=None):
    """Get interface data for one or more interfaces.
    Returns data for all useful interfaces if no specific interface is provided.

    """
    if interface:
        interface_ips = get_ips_for_interface(interface)
    else:
        interface_ips = []
        for int_ in netifaces.interfaces():
            interface_ips += get_ips_for_interface(int_)
    return sorted(interface_ips, key=lambda tup: tup[1])


def do_bind(args):
    if args.show_net:
        interface_ips = get_interface_data()
        choices = []
        for interface, ip_addr in interface_ips:
            print '%s (%s)' % (ip_addr, interface)
        return

    if not args.bind_ip:
        # Guess the IP.
        interfaces = get_interface_data(args.bind_int)
        if not interfaces:
            args.error('No useable interfaces found. Are you connected '
                       'to a network that your device will be able to "see"?')
        if len(interfaces) > 1:
            prompt = 'Not sure which IP to use. Please select one [1]:'
            interface_ips = get_interface_data()
            choices = []
            for interface, ip_addr in interface_ips:
                choices.append(('%s (%s)' % (ip_addr, interface), ip_addr))

            choice = select(choices, prompt=prompt)
            args.bind_ip = choice[1]
        else:
            # Get the only ip we found.
            args.bind_ip = interfaces[0][1]

    print 'About to bind host "{host}" on device to IP "{ip}"'.format(
            host=args.bind_host, ip=args.bind_ip)
    td = tempfile.mkdtemp()
    try:
        with pushd(td):
            sh('adb remount')
            sh('adb pull /system/etc/hosts ./')
            with open('./hosts') as f:
                lines = f.readlines()
                newlines = []
                for ln in lines:
                    if (ln.strip().endswith(args.bind_host) or
                        ln.startswith('# ezboot:')):
                        # Remove the old IP binding and comments.
                        continue
                    newlines.append(ln)
                newlines.append('# ezboot: bind command added this:\n')
                newlines.append('{ip}\t\t    {host}\n'
                                .format(ip=args.bind_ip,
                                        host=args.bind_host))

            with open('./new-hosts', 'w') as f:
                f.write(''.join(newlines))
            sh('adb push ./new-hosts /system/etc/hosts')
    finally:
        shutil.rmtree(td)
    print 'Great success'


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
                  '/mozilla-b2g18-unagi-eng/latest/unagi.zip'),
        'inari': ('https://pvtbuilds.mozilla.org/pvt/mozilla.org/b2gotoro/nightly'
                  '/mozilla-b2g18-inari-eng/latest/inari.zip'),
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


def install_desktop(args):
    if not args.platform:
        if sys.platform == 'darwin':
            args.platform = 'mac64'
        else:
            raise NotImplementedError(
                "Sorry, I'm lazy. Please submit a patch for your "
                "platform %r." % sys.platform)
    attr = '%s_url' % args.platform.replace('-', '_')
    url = getattr(args, attr, None)
    if not url:
        raise ValueError(
            "That's odd, we don't have a URL for your platform. "
            "Guessed: args.%s" % attr)

    print 'Downloading %s' % url
    dest = os.path.join(args.work_dir, 'last-desktop-build')
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.mkdir(dest)

    with pushd(dest):
        # TODO: librarify this progress code.
        res = requests.get(url, stream=True)
        if res.status_code != 200:
            args.error('Got %s from %s. Try again later maybe'
                       % (res.status_code, url))
        total_bytes = int(res.headers['content-length'])
        filedest = open(os.path.basename(url), 'wb')
        print 'Saving %s' % filedest.name
        dots = 1
        chars = ['.', ' ']
        bytes_down = 0
        width = TERM_WIDTH
        with filedest as fp:
            for chunk in res.iter_content(chunk_size=CHUNK_SIZE):
                bytes_down += CHUNK_SIZE
                fp.write(chunk)
                sys.stdout.write("\r%s%s %2.2f%%"
                                 % (chars[0] * dots,
                                    chars[1] * (width - dots),
                                    100.0 * bytes_down / total_bytes))
                sys.stdout.flush()
                dots += 1
                if dots >= width:
                    dots = 1
                    chars.reverse()
            print ''  # finish progress indicator

        if args.platform == 'mac64':
            sh('hdiutil mount %s' % filedest.name)
            sh('cp -r /Volumes/B2G/B2G.app ./')
            sh('hdiutil unmount /Volumes/B2G/')
            os.unlink(filedest.name)

            print 'NOTE: you still need to build a Gaia profile'
            print 'Ready to run: '
            print ('%s/B2G.app/Contents/MacOS/b2g-bin -jsconsole -profile ...'
                   % os.path.abspath(dest))
        else:
            raise NotImplementedError(
                'Not sure how to install for your platform %r'
                % args.platform)


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
        width = TERM_WIDTH
        for chunk in res.iter_content(chunk_size=CHUNK_SIZE):
            bytes_down += CHUNK_SIZE
            zipdest.write(chunk)
            sys.stdout.write("\r%s%s %2.2f%%" % (chars[0] * dots,
                                         chars[1] * (width - dots),
                                         100.0 * bytes_down / total_bytes))
            sys.stdout.flush()
            dots += 1
            if dots >= width:
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
        mc.find_element(*_verify_start_button).tap()
    except TimeoutException:
        print 'Not a new account? Trying to log in to existing account'
        # Logging into an exisiting account:
        password_field = mc.find_element(*_password_input_locator)
        password_field.send_keys(password)
        wait_for_element_displayed(mc, *_returning_button_locator)
        mc.find_element(*_returning_button_locator).tap() #.click()

    print 'You should be logged in now'


def setup_certs(args):
    device_id = args.flash_device_id

    # The device string for unagis is fixed.
    if args.flash_device.lower() == 'unagi' and not device_id:
        device_id = 'full_unagi'

    # Check connected devices to be sure.
    devices = sh_output('adb devices -l')

    if device_id not in devices or not device_id:
        raise ValueError('Check your device string using '
                         '"adb devices -l" and put it in your '
                         'ini file as flash_device_id. if you have '
                         'problems use the string prefixed with '
                         '"usb:"')

    def setup_dev():
        certs_path = os.path.abspath(args.certs_path)

        with pushd(args.work_dir):
            path = 'marketplace-certs'

            if not os.path.exists(path):
                print 'Cloning certificates for the first itme.'
                sh('git clone https://github.com/briansmith/'
                   'marketplace-certs.git %s'
                   % os.path.join(args.work_dir, path))
            else:
                # pull the latest changes from remote
                print 'Updating certificates from remote.'
                with pushd(path):
                    sh('git pull')

            with pushd(path):
                sh("./change_trusted_servers.sh '%s' "
                   "'https://marketplace-dev.allizom.org,"
                   "https://marketplace.firefox.com'" % device_id)
                sh("./push_certdb.sh '%s' %s" %  (device_id, certs_path))
            sh('adb reboot')

    if args.env is None:
        args.error('Provide which version of dev certs you want to install. '
                   'For example, --dev.')

    for env in args.env:
        func = locals().get('setup_%s' % env, None)
        if func is not None:
            print 'Installing marketplace %s certs...' % env
            func()


def install_marketplace(args):
    # install marketplace dev
    def install_dev():
        args.app_url = 'https://marketplace-dev.allizom.org/app/marketplace'
        args.prod = False
        args.app = None
        args.manifest = None

        install_app(args)

    if args.env is None:
        args.error('Provide which version of marketplace you want to install. '
                   'For example, --dev.')

    for env in args.env:
        func = locals().get('install_%s' % env, None)
        if func is not None:
            print 'Installing Marketplace %s' % env
            func()


def install_app(args):
    def confirm_installation():
        _yes_button_locator = ('id', 'app-install-install-button')

        wait_for_element_displayed(mc, *_yes_button_locator)
        mc.find_element(*_yes_button_locator).tap()
        wait_for_element_not_displayed(mc, *_yes_button_locator)

        print 'App successfully installed.'

    # marketplace loading fragment locator
    _loading_fragment_locator = ('css selector', 'div#splash-overlay')
    _search_locator = ('id', 'search-q')

    if not args.app and not args.manifest and not args.app_url:
        args.error('Provide either app name (using --app), URL of app\'s '
                   'manifest file (using --manifest) or URL of the app '
                   'on marketpalce (using --app_url).')

    mc = get_marionette(args)
    lockscreen = LockScreen(mc)
    lockscreen.unlock()

    apps = GaiaApps(mc)
    apps.kill_all()

    no_internet_error = ('Unable to download app.\nReason: You are probably '
                         'not connected to internet on your device.')

    if args.manifest:
        mc.execute_script('navigator.mozApps.install("%s")' % args.manifest)
        try:
            confirm_installation()
        except TimeoutException, exc:
            print '** %s: %s' % (exc.__class__.__name__, exc)
            args.error(no_internet_error)
        return

    if args.prod:
        marketplace_app = 'Marketplace'
        marketplace_url = 'https://marketplace.firefox.com/'
    else:
        marketplace_app = 'Marketplace Dev'
        marketplace_url = 'https://marketplace-dev.allizom.org/'

    if args.app_url:
        args.browser = True
        marketplace_url = args.app_url

    # apps.kill_all()
    if args.browser:
        browser = Browser(mc)
        browser.launch()
        browser.go_to_url(marketplace_url)

        browser.switch_to_content()
        browser.wait_for_element_not_displayed(*_loading_fragment_locator)

    marketplace = Marketplace(mc, marketplace_app)

    if not args.browser:
        try:
            marketplace.launch()
        except AssertionError:
            e = ('Marketplace Dev app is not installed. Install it using '
                 'install_mkt --dev or use --browser to install apps '
                 'from the browser directly.')
            args.error(e)

        if args.prod:
            marketplace.switch_to_marketplace_frame()

    if not args.app_url:
        try:
            marketplace.wait_for_element_displayed(*_search_locator)
            results = marketplace.search(args.app)
        except NoSuchElementException, exc:
            print '** %s: %s' % (exc.__class__.__name__, exc)
            args.error(no_internet_error)

        try:
            results.search_results[0].tap_install_button()
        except IndexError:
            args.error('Error: App not found.')
    else:
        _install_button_locator = ('css selector', '.button.product.install')
        marketplace.wait_for_element_displayed(*_install_button_locator)
        mc.find_element(*_install_button_locator).tap()
        mc.switch_to_frame()

    confirm_installation()


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
    cmd.add_argument('--flash_device_id', default=None,
                     help='The device identifier as reported by adb devices -l (usb:<blah>)')


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

    desktop = sub_parser('desktop', help='Downloads and installs desktop b2g')
    desktop.set_defaults(func=install_desktop)
    desktop.add_argument('--platform',
                         help='Your desktop platform. This option overrides '
                              'the auto-detected choice.',
                         choices=['mac64', 'linux-i686', 'linux-x86_64', 'win32'])
    base_url = 'http://ftp.mozilla.org/pub/mozilla.org/b2g/nightly/latest-mozilla-b2g18'
    desktop.add_argument('--mac64-url', help='64-bit Mac OS X B2G URL',
                         default='%s/b2g-18.0.multi.mac64.dmg' % base_url)
    desktop.add_argument('--linux-i686-url', help='Linux i686 B2G URL',
                         default='%s/b2g-18.0.multi.linux-i686.tar.bz2' % base_url)
    desktop.add_argument('--linux-x86_64-url', help='Linux x86_64 B2G URL',
                         default='%s/b2g-18.0.multi.linux-x86_64.tar.bz2' % base_url)
    desktop.add_argument('--win32-url', help='32-bit Windows B2G URL',
                         default='%s/b2g-18.0.multi.win32.zip' % base_url)

    bind = sub_parser('bind', help='Bind a hostname on your mobile device '
                                   'to your local server')
    bind.set_defaults(func=do_bind)
    bind.add_argument('--bind_host', help='hostname',
                      default='fireplace.local')
    bind.add_argument('--bind_ip', help='IP to bind to. If empty, the IP '
                                        'will be discovered.')
    bind.add_argument('--bind_int', help='Network interface to guess an IP from',
                      default=None)
    bind.add_argument('--show_net',
                      help='Show network info but do not bind anything.',
                      action='store_true')

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

    mkt_certs = sub_parser('mkt_certs', help='Setup certs for packaged '
                                             'marketplace for testing.')
    mkt_certs.add_argument('--certs_path',
                           help='Path to the directory that has dev certs.',
                           required=True)
    # we can add more options like this whenever we want
    mkt_certs.add_argument('--dev', help='Setup certs for marketplace dev.',
                           dest='env', action='append_const', const='dev')
    mkt_certs.set_defaults(func=setup_certs)

    install_mp = sub_parser('install_mkt', help='Install marketplace app.')
    install_mp.add_argument('--dev', help='Install marketplace dev.',
                            dest='env', action='append_const', const='dev')
    install_mp.set_defaults(func=install_marketplace)

    install = sub_parser('install', help='Install an app on device using '
                                         'manifest file or marketplace.')
    install.add_argument('--app', help='Name of the app you want to install '
                                       'from the marketplace.')
    install.add_argument('--browser', help='If you want to use marketplace in'
                                           ' the browser.',
                         action='store_true')
    install.add_argument('--prod', help='Install from Marketplace (production)'
                                        ' instead of Marketplace Dev.',
                         action='store_true')
    install.add_argument('--manifest', help='Path to manifest file.')
    install.add_argument('--app_url', help='URL of the app on marketplace.')
    install.set_defaults(func=install_app)

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
