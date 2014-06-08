#!/usr/bin/python

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    config,
    is_relation_made,
    log,
    ERROR,
    relation_ids,
    relation_get,
    relation_set,
    service_name,
    unit_get,
    UnregisteredHookError,
)

from charmhelpers.core.host import (
    restart_on_change,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    filter_installed_packages,
)

from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    openstack_upgrade_available,
)

from charmhelpers.contrib.storage.linux.ceph import ensure_ceph_keyring
from charmhelpers.payload.execd import execd_preinstall

from nova_compute_utils import (
    create_libvirt_secret,
    determine_packages,
    import_authorized_keys,
    import_keystone_ca_cert,
    initialize_ssh_keys,
    migration_enabled,
    network_manager,
    neutron_plugin,
    do_openstack_upgrade,
    public_ssh_key,
    restart_map,
    register_configs,
    NOVA_CONF,
    QUANTUM_CONF, NEUTRON_CONF,
    ceph_config_file, CEPH_SECRET,
    enable_shell, disable_shell,
    fix_path_ownership
)

from nova_compute_proxy import (
    configure_power,
    launch_power
)


from nova_compute_context import CEPH_SECRET_UUID

hooks = Hooks()
CONFIGS = register_configs()


@hooks.hook()
def install():
    execd_preinstall()
    configure_installation_source(config('openstack-origin'))
    apt_update()
    apt_install(['nova-common', 'libvirt-bin', 'fabric'], fatal=True)


@hooks.hook('config-changed')
@restart_on_change(restart_map())
def config_changed():
    global CONFIGS
    if openstack_upgrade_available('nova-common'):
        CONFIGS = do_openstack_upgrade()

    if migration_enabled() and config('migration-auth-type') == 'ssh':
        # Check-in with nova-c-c and register new ssh key, if it has just been
        # generated.
        initialize_ssh_keys()

    if config('enable-resize') is True:
        enable_shell(user='nova')
        initialize_ssh_keys(user='nova')
    else:
        disable_shell(user='nova')

    if config('instances-path') is not None:
        fp = config('instances-path')
        fix_path_ownership(fp, user='nova')

    [compute_joined(rid) for rid in relation_ids('cloud-compute')]

    CONFIGS.write_all()


@hooks.hook('amqp-relation-joined')
def amqp_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 username=config('rabbit-user'),
                 vhost=config('rabbit-vhost'))


@hooks.hook('amqp-relation-changed')
@hooks.hook('amqp-relation-departed')
@restart_on_change(restart_map())
def amqp_changed():
    if 'amqp' not in CONFIGS.complete_contexts():
        log('amqp relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)

    if network_manager() == 'quantum' and neutron_plugin() == 'ovs':
        CONFIGS.write(QUANTUM_CONF)
    if network_manager() == 'neutron' and neutron_plugin() == 'ovs':
        CONFIGS.write(NEUTRON_CONF)


@hooks.hook('shared-db-relation-joined')
def db_joined(rid=None):
    if is_relation_made('pgsql-db'):
        # error, postgresql is used
        e = ('Attempting to associate a mysql database when there is already '
             'associated a postgresql one')
        log(e, level=ERROR)
        raise Exception(e)

    relation_set(relation_id=rid,
                 nova_database=config('database'),
                 nova_username=config('database-user'),
                 nova_hostname=unit_get('private-address'))


@hooks.hook('pgsql-db-relation-joined')
def pgsql_db_joined():
    if is_relation_made('shared-db'):
        # raise error
        e = ('Attempting to associate a postgresql database when'
             ' there is already associated a mysql one')
        log(e, level=ERROR)
        raise Exception(e)

    relation_set(database=config('database'))


@hooks.hook('shared-db-relation-changed')
@restart_on_change(restart_map())
def db_changed():
    if 'shared-db' not in CONFIGS.complete_contexts():
        log('shared-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)


@hooks.hook('pgsql-db-relation-changed')
@restart_on_change(restart_map())
def postgresql_db_changed():
    if 'pgsql-db' not in CONFIGS.complete_contexts():
        log('pgsql-db relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)


@hooks.hook('image-service-relation-changed')
@restart_on_change(restart_map())
def image_service_changed():
    if 'image-service' not in CONFIGS.complete_contexts():
        log('image-service relation incomplete. Peer not ready?')
        return
    CONFIGS.write(NOVA_CONF)


@hooks.hook('cloud-compute-relation-joined')
def compute_joined(rid=None):
    if migration_enabled():
        auth_type = config('migration-auth-type')
        settings = {
            'migration_auth_type': auth_type
        }
        if auth_type == 'ssh':
            settings['ssh_public_key'] = public_ssh_key()
        relation_set(relation_id=rid, **settings)
    if config('enable-resize'):
        settings = {
            'nova_ssh_public_key': public_ssh_key(user='nova')
        }
        relation_set(relation_id=rid, **settings)
    launch_power()


@hooks.hook('cloud-compute-relation-changed')
@restart_on_change(restart_map())
def compute_changed():
    # rewriting all configs to pick up possible net or vol manager
    # config advertised from controller.
    CONFIGS.write_all()
    import_authorized_keys()
    import_authorized_keys(user='nova', prefix='nova')
    import_keystone_ca_cert()
    configure_power()


@hooks.hook('ceph-relation-joined')
@restart_on_change(restart_map())
def ceph_joined():
    log('Nothing to do here')


@hooks.hook('ceph-relation-changed')
@restart_on_change(restart_map())
def ceph_changed():
    if 'ceph' not in CONFIGS.complete_contexts():
        log('ceph relation incomplete. Peer not ready?')
        return
    svc = service_name()
    if not ensure_ceph_keyring(service=svc):
        log('Could not create ceph keyring: peer not ready?')
        return
    CONFIGS.write(ceph_config_file())
    CONFIGS.write(CEPH_SECRET)
    CONFIGS.write(NOVA_CONF)

    # With some refactoring, this can move into NovaComputeCephContext
    # and allow easily extended to support other compute flavors.
    if config('virt-type') in ['kvm', 'qemu', 'lxc']:
        create_libvirt_secret(secret_file=CEPH_SECRET,
                              secret_uuid=CEPH_SECRET_UUID,
                              key=relation_get('key'))


@hooks.hook('amqp-relation-broken',
            'ceph-relation-broken',
            'image-service-relation-broken',
            'shared-db-relation-broken',
            'pgsql-db-relation-broken')
@restart_on_change(restart_map())
def relation_broken():
    CONFIGS.write_all()


@hooks.hook('upgrade-charm')
def upgrade_charm():
    for r_id in relation_ids('amqp'):
        amqp_joined(relation_id=r_id)


@hooks.hook('nova-ceilometer-relation-changed')
@restart_on_change(restart_map())
def nova_ceilometer_relation_changed():
    CONFIGS.write_all()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))


if __name__ == '__main__':
    main()
