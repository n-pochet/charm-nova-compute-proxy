# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from charmhelpers.fetch import (
    apt_install,
)

try:
    from fabric.api import (
        sudo,
        put,
        env
    )
except ImportError:
    apt_install('fabric', fatal=True)
    from fabric.api import (
        sudo,
        put,
        env
    )


def yum_update():
    sudo('yum update -y')


def copy_file_as_root(src, dest):
    put(src, dest, use_sudo=True)


def yum_install(packages):
    sudo('yum install --skip-broken -y {}'.format(' '.join(packages)))


def restart_service(service):
    sudo('systemctl restart {}'.format(service))


def start_service(service):
    sudo('systemctl start {}'.format(service))


def enable_service(service):
    sudo('systemctl enable {}'.format(service))


def add_bridge(bridge_name):
    sudo('ovs-vsctl -- --may-exist add-br {}'.format(bridge_name))


def add_bridge_port(bridge_name, port):
    sudo('ovs-vsctl -- --may-exist add-port {} {}'.format(bridge_name,
                                                          port))
    sudo('ip link set {} up'.format(port))
    sudo('ip link set {} promisc on'.format(port))


def enable_shell(user):
    sudo('usermod -s /bin/bash {}'.format(user))


def disable_shell(user):
    sudo('usermod -s /bin/false {}'.format(user))


def fix_path_ownership(path, user='nova'):
    sudo('chown {} {}'.format(user, path))


def fix_selinux_permission(path):
    sudo('chcon -vv --user=system_u --role=object_r --type=etc_t --range=s0 '
         '{}'.format(path))


def allow_gre_firewalld():
    sudo('firewall-cmd --permanent --direct \
         --add-rule ipv4 filter INPUT 0 -p gre -j ACCEPT')


def fix_local_ip(f):
    sudo('sed -i "s!LOCAL_IP!{}!g" {}'.format(env.host, f))
