# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#

import contextlib
from quantum.openstack.common import log as logging

LOG = logging.getLogger("quantum.quark.base")


def request_check(limits):
    """Decorating function which requests a limit check in the plugin."""
    def passthrough(func):
        def with_request_check(self, *args, **kwargs):
            unchecked_limits = [l for l in limits if
                                self.limits.get(l, True) is not False]
            if unchecked_limits:
                LOG.warning("Driver limit checks on %s expected but "
                            "not performed in plugin." % unchecked_limits)
            return func(self, *args, **kwargs)
        return with_request_check
    return passthrough


class BaseDriver(object):
    """Base interface for all Quark drivers.

    Usable as a replacement for the sample plugin.
    """
    def __init__(self):
        self.limits = {}

    def load_config(self, path):
        LOG.info("load_config %s" % path)

    def get_connection(self):
        LOG.info("get_connection")

    @contextlib.contextmanager
    def limits_checked(self, limits):
        orig_limits = {}
        for l in limits:
            self.limits[l], orig_limits[l] = False, self.limits.get(l, False)
        yield orig_limits
        self.limits.update(orig_limits)

    def get_driver_limits(self, limits):
        return dict(self.limits.get(l, None) for l in limits)

    def create_network(self, tenant_id, network_name, tags=None,
                       network_id=None, **kwargs):
        LOG.info("create_network %s %s %s" % (tenant_id, network_name,
                                              tags))

    def delete_network(self, context, network_id):
        LOG.info("delete_network %s" % network_id)

    def create_port(self, context, network_id, port_id, **kwargs):
        LOG.info("create_port %s %s %s" % (context.tenant_id, network_id,
                                           port_id))
        return {"uuid": port_id}

    def update_port(self, context, port_id, **kwargs):
        LOG.info("update_port %s %s" % (context.tenant_id, port_id))
        return {"uuid": port_id}

    def delete_port(self, context, port_id, **kwargs):
        LOG.info("delete_port %s %s" % (context.tenant_id, port_id))

    def create_security_group(self, context, group_name, **group):
        LOG.info("Creating security profile %s for tenant %s" %
                 (group_name, context.tenant_id))

    def delete_security_group(self, context, group_id, **kwargs):
        LOG.info("Deleting security profile %s for tenant %s" %
                (group_id, context.tenant_id))

    def create_security_group_rule(self, context, group_id, rule):
        LOG.info("Creating security rule on group %s for tenant %s" %
                (group_id, context.tenant_id))

    def delete_security_group_rule(self, context, group_id, rule):
        LOG.info("Deleting security rule on group %s for tenant %s" %
                (group_id, context.tenant_id))
