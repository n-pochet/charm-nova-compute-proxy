#!/usr/bin/python
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

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    config,
    log,
    relation_ids,
    relation_set,
    UnregisteredHookError,
)

from charmhelpers.fetch import (
    apt_install,
)

from nova_compute_utils import (
    restart_map,
    register_configs,
    NOVA_CONF,
    assess_status,
)
from nova_compute_proxy import (
    REMOTEProxy,
    restart_on_change,
)

hooks = Hooks()
CONFIGS = register_configs()
proxy = REMOTEProxy(user=config('remote-user'),
                    ssh_key=config('remote-key'),
                    hosts=config('remote-hosts'),
                    repository=config('remote-repos'),
                    password=config('remote-password'))


@hooks.hook('install.real')
def install():
    apt_install(['fabric'], fatal=True)
    proxy.install()


@hooks.hook('config-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def config_changed():
    proxy.configure()
    if config('instances-path') is not None:
        proxy.fix_path_ownership(config('instances-path'), user='nova')

    [compute_joined(rid) for rid in relation_ids('cloud-compute')]
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'),
                 vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@hooks.hook('amqp-relation-departed')
@restart_on_change(restart_map(), proxy.restart_service)
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('image-service-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def image_service_changed():
    if 'image-service' not in CONFIGS.complete_contexts():
        log('image-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)
    proxy.commit()


@hooks.hook('cloud-compute-relation-joined')
def compute_joined(rid=None):
    pass


@hooks.hook('cloud-compute-relation-changed',
            'neutron-plugin-api-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def compute_changed():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('amqp-relation-broken',
            'image-service-relation-broken',
            'neutron-plugin-api-relation-broken')
@restart_on_change(restart_map(), proxy.restart_service)
def relation_broken():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    proxy.install()
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)


@hooks.hook('nova-ceilometer-relation-changed')
@restart_on_change(restart_map(), proxy.restart_service)
def nova_ceilometer_relation_changed():
    CONFIGS.write_all()
    proxy.commit()


@hooks.hook('update-status')
def update_status():
    log('Updating status.')
    assess_status(CONFIGS)


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    assess_status(CONFIGS)
