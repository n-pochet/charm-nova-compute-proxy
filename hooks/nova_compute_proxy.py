import os
import tempfile
from collections import OrderedDict

from charmhelpers.core.hookenv import (
    log,
    service_name
)
from charmhelpers.core.host import (
    mkdir,
    file_hash
)
from charmhelpers.fetch import (
    apt_install,
)
from fabfile import (
    add_bridge,
    yum_update,
    copy_file_as_root,
    yum_install,
    restart_service,
    enable_shell,
    disable_shell,
    fix_path_ownership
)

try:
    import jinja2
except ImportError:
    apt_install('python-jinja2', fatal=True)
    import jinja2

try:
    from fabric.api import env
    from fabric.tasks import execute
except ImportError:
    apt_install('fabric', fatal=True)
    from fabric.api import env
    from fabric.tasks import execute

TEMPLATE_DIR = 'templates'

PACKAGES = ['openstack-nova-compute',
            'openstack-neutron',
            'openstack-neutron-openvswitch',
            'openstack-neutron-linuxbridge',
            'python-neutronclient',
            'ceilometer-compute-agent']

CONFIG_FILES = [
    '/etc/neutron/neutron.conf',
    '/etc/neutron/plugins/ml2/ml2_conf.ini',
    '/etc/nova/nova.conf',
    '/etc/ceilometer/ceilometer.conf']

SERVICES = ['libvirtd', 'compute', 'neutron']



class POWERProxy():

    def __init__(self, user, ssh_key, hosts,
                 repository):
        if None in [user, ssh_key, hosts, repository]:
            raise Exception('Missing configuration')
        self.user = user
        self.hosts = hosts.split()
        self.respository = repository
        self.conf_path = os.path.join('/var/lib/charm',
                                      service_name())
        self._write_key(ssh_key)
        self._init_fabric()

    def _write_key(self, key):
        path = os.path.join('/var/lib', service_name())
        self.key_filename = os.path.join(path, 'ssh_key')
        mkdir(path)
        with open(self.key_filename, 'w') as f:
            f.write(key)

    def _init_fabric(self):
        env.warn_only = True
        env.connection_attempts = 10
        env.timeout = 10
        env.user = self.user
        env.key_filename= self.key_filename
        env.hosts = self.hosts

    def install(self):
        self._setup_hosts()
        self._setup_yum()
        self._install_packages()

    def _setup_hosts(self):
        log('Setting up hosts')
        execute(yum_update)
        
    def _setup_yum(self):
        log('Setup yum')
        context = {'yum_repo': self.repository}
        _, filename = tempfile.mkstemp()
        with open(filename, 'w') as f:
            f.write(_render_template('yum.template', context))
        execute(copy_file_as_root, filename, '/etc/yum.repos.d/openstack-power.repo')
        os.unlink(filename)

    def _install_packages(self):
        execute(yum_install, PACKAGES)

    def configure(self):
        self.add_bridge()

    def copy_file(self, target):
        execute(copy_file_as_root,
                os.path.join(self.conf_path, target),
                target)

    def restart_service(self, service):
        execute(restart_service, service)

    def add_bridge(self):
        execute(add_bridge)

    def enable_shell(self, user):
        execute(enable_shell, user)

    def disable_shell(self, user):
        execute(disable_shell, user)
    
    def fix_path_ownership(self, user, path):
        execute(fix_path_ownership, user, path)
    
    def commit(self):
        for f in CONFIG_FILES:
            if os.path.exists(f):
                self.copy_file(f)


def _render_template(template_name, context, template_dir=TEMPLATE_DIR):
    templates = jinja2.Environment(
            loader=jinja2.FileSystemLoader(template_dir))
    template = templates.get_template(template_name)
    return template.render(context)


def restart_on_change(restart_map, func):
    """Restart services using provided function based on configuration files changing"""
    def wrap(f):
        def wrapped_f(*args):
            checksums = {}
            for path in restart_map:
                checksums[path] = file_hash(path)
            f(*args)
            restarts = []
            for path in restart_map:
                if checksums[path] != file_hash(path):
                    restarts += restart_map[path]
            services_list = list(OrderedDict.fromkeys(restarts))
            for service_name in services_list:
                func(service_name)
        return wrapped_f
    return wrap