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
#    under the License.

"""
NVP client driver for Quark
"""

from oslo.config import cfg

import aiclib
import contextlib
from quantum.extensions import securitygroup as sg_ext
from quantum.openstack.common import log as logging

from quark.drivers import base
from quark import exceptions


LOG = logging.getLogger("quantum.quark.nvplib")

CONF = cfg.CONF

nvp_opts = [
    cfg.IntOpt('max_ports_per_switch',
               default=0,
               help=_('Maximum amount of NVP ports on an NVP lswitch')),
    cfg.StrOpt('default_tz',
               help=_('The default transport zone UUID')),
    cfg.MultiStrOpt('controller_connection',
                    default=[],
                    help=_('NVP Controller connection string')),
    cfg.IntOpt('max_rules_per_group',
               default=30,
               help=_('Maxiumum size of NVP SecurityRule list per group')),
    cfg.IntOpt('max_rules_per_port',
               default=30,
               help=_('Maximum rules per NVP lport across all groups')),
]

physical_net_type_map = {
    "stt": "stt",
    "gre": "gre",
    "flat": "bridge",
    "bridge": "bridge",
    "vlan": "bridge",
    "local": "local"
}

CONF.register_opts(nvp_opts, "NVP")


def request_check(limits):
    """Decorating function which requests a limit check in the plugin."""
    def passthrough(func):
        def with_request_check(self, *args, **kwargs):
            unchecked_limits = [(limit if (self.limits.get(limit, True)
                                is not False) else None) for limit in limits]
            if any(unchecked_limits):
                LOG.warning("Driver limit checks on %s expected but "
                            "not performed in plugin." % unchecked_limits)
            return func(self, *args, **kwargs)
        return with_request_check
    return passthrough


class NVPDriver(base.BaseDriver):
    def __init__(self):
        self.nvp_connections = []
        self.conn_index = 0
        self.limits = {'max_ports_per_switch': 0,
                       'max_rules_per_group': 0,
                       'max_rules_per_port': 0}

    def load_config(self, path):
        #NOTE(mdietz): What does default_tz actually mean?
        #              We don't have one default.
        default_tz = CONF.NVP.default_tz
        LOG.info("Loading NVP settings " + str(default_tz))
        connections = CONF.NVP.controller_connection
        self.limits.update({
            'max_ports_per_switch': CONF.NVP.max_ports_per_switch,
            'max_rules_per_group': CONF.NVP.max_rules_per_group,
            'max_rules_per_port': CONF.NVP.max_rules_per_port})
        LOG.info("Loading NVP settings " + str(connections))
        for conn in connections:
            (ip, port, user, pw, req_timeout,
             http_timeout, retries, redirects) = conn.split(":")

            self.nvp_connections.append(dict(ip_address=ip,
                                        port=port,
                                        username=user,
                                        password=pw,
                                        req_timeout=req_timeout,
                                        http_timeout=http_timeout,
                                        retries=retries,
                                        redirects=redirects,
                                        default_tz=default_tz))

    def get_connection(self):
        conn = self.nvp_connections[self.conn_index]
        if "connection" not in conn:
            scheme = conn["port"] == "443" and "https" or "http"
            uri = "%s://%s:%s" % (scheme, conn["ip_address"], conn["port"])
            user = conn['username']
            passwd = conn['password']
            conn["connection"] = aiclib.nvp.Connection(uri,
                                                       username=user,
                                                       password=passwd)
        return conn["connection"]

    @contextlib.contextmanager
    def limits_checked(self, limits):
        """Inform the driver of hard limit checks performed in plugin.

        Ex.:
        with net_driver.limits_checked(['example_limit']):
            net_driver.example_call()

        : param limits: the limits which the plugin is checking.
        """
        orig_limits = {}
        for limit in limits:
            orig_limits[limit], self.limits[limit] = (self.limits[limit],
                                                      False)
        yield orig_limits
        self.limits.update(orig_limits)

    def get_driver_limits(self, limits):
        """Returns the driver limits requested.

        : param limits: list with keys of requested limits
        """
        driver_limits = dict((k, v) for (k, v) in self.limits.items()
                             if k in limits)
        return driver_limits

    def create_network(self, context, network_name, tags=None,
                       network_id=None, **kwargs):
        return self._lswitch_create(context, network_name, tags,
                                    network_id, **kwargs)

    def delete_network(self, context, network_id):
        lswitches = self._lswitches_for_network(context, network_id).results()
        connection = self.get_connection()
        for switch in lswitches["results"]:
            LOG.debug("Deleting lswitch %s" % switch["uuid"])
            connection.lswitch(switch["uuid"]).delete()

    def create_port(self, context, network_id, port_id,
                    status=True, security_groups=[], allowed_pairs=[]):
        tenant_id = context.tenant_id
        lswitch = self._create_or_choose_lswitch(context, network_id)
        connection = self.get_connection()
        port = connection.lswitch_port(lswitch)
        port.admin_status_enabled(status)
        port.allowed_address_pairs(allowed_pairs)
        nvp_group_ids = self._get_security_groups_for_port(context,
                                                           security_groups)
        port.security_profiles(nvp_group_ids)
        tags = [dict(tag=network_id, scope="quantum_net_id"),
                dict(tag=port_id, scope="quantum_port_id"),
                dict(tag=tenant_id, scope="os_tid")]
        LOG.debug("Creating port on switch %s" % lswitch)
        port.tags(tags)
        res = port.create()
        res["lswitch"] = lswitch
        return res

    def update_port(self, context, port_id, status=True,
                    security_groups=[], allowed_pairs=[]):
        connection = self.get_connection()
        lswitch_id = self._lswitch_from_port(context, port_id)
        port = connection.lswitch_port(lswitch_id, port_id)
        nvp_group_ids = self._get_security_groups_for_port(context,
                                                           security_groups)
        if nvp_group_ids:
            port.security_profiles(nvp_group_ids)
        if allowed_pairs:
            port.allowed_address_pairs(allowed_pairs)
        port.admin_status_enabled(status)
        return port.update()

    def delete_port(self, context, port_id, **kwargs):
        connection = self.get_connection()
        lswitch_uuid = kwargs.get('lswitch_uuid', None)
        if not lswitch_uuid:
            lswitch_uuid = self._lswitch_from_port(context, port_id)
        LOG.debug("Deleting port %s from lswitch %s" % (port_id, lswitch_uuid))
        connection.lswitch_port(lswitch_uuid, port_id).delete()

    def _get_network_details(self, context, network_id, switches):
        name, phys_net, phys_type, segment_id = None, None, None, None
        for res in switches["results"]:
            name = res["display_name"]
            for zone in res["transport_zones"]:
                phys_net = zone["zone_uuid"]
                phys_type = zone["transport_type"]
                if "binding_config" in zone:
                    binding = zone["binding_config"]
                    segment_id = binding["vlan_translation"][0]["transport"]
                break
            return dict(network_name=name, phys_net=phys_net,
                        phys_type=phys_type, segment_id=segment_id)
        return {}

    @request_check(['max_rules_per_group'])
    def create_security_group(self, context, group_name, **group):
        tenant_id = context.tenant_id
        connection = self.get_connection()
        group_id = group.get('group_id')
        profile = connection.securityprofile()
        if group_name:
            profile.display_name(group_name)
        ingress_rules = group.get('port_ingress_rules', [])
        egress_rules = group.get('port_egress_rules', [])

        limit = self.limits['max_rules_per_group']
        if (limit is not False and
                len(ingress_rules) + len(egress_rules) > limit):
            raise exceptions.DriverLimitReached(limit="rules per group")

        if egress_rules:
            profile.port_egress_rules(egress_rules)
        if ingress_rules:
            profile.port_ingress_rules(ingress_rules)
        tags = [dict(tag=group_id, scope="quantum_group_id"),
                dict(tag=tenant_id, scope="os_tid")]
        LOG.debug("Creating security profile %s" % group_name)
        profile.tags(tags)
        return profile.create()

    def delete_security_group(self, context, group_id):
        guuid = self._get_security_group_id(context, group_id)
        connection = self.get_connection()
        LOG.debug("Deleting security profile %s" % group_id)
        connection.securityprofile(guuid).delete()

    @request_check(['max_rules_per_group'])
    def update_security_group(self, context, group_id, **group):
        query = self._get_security_group(context, group_id)
        connection = self.get_connection()
        profile = connection.securityprofile(query.get('uuid'))

        ingress_rules = group.get('port_ingress_rules',
                                  query.get('logical_port_ingress_rules'))
        egress_rules = group.get('port_egress_rules',
                                 query.get('logical_port_egress_rules'))

        limit = self.limits['max_rules_per_group']
        if (limit is not False and
                len(ingress_rules) + len(egress_rules) > limit):
            raise exceptions.DriverLimitReached(limit="rules per group")

        if group.get('name', None):
            profile.display_name(group['name'])
        if group.get('port_ingress_rules', None) is not None:
            profile.port_ingress_rules(ingress_rules)
        if group.get('port_egress_rules', None) is not None:
            profile.port_egress_rules(egress_rules)
        return profile.update()

    def _update_security_group_rules(self, context, group_id, rule, operation,
                                     checks):
        groupd = self._get_security_group(context, group_id)
        direction, secrule = self._get_security_group_rule_object(context,
                                                                  rule)
        rulelist = groupd['logical_port_%s_rules' % direction]
        for check in checks:
            if not check(secrule, rulelist):
                raise checks[check]
        getattr(rulelist, operation)(secrule)

        LOG.debug("%s rule on security group %s" % (operation, groupd['uuid']))
        group = {'port_%s_rules' % direction: rulelist}
        return self.update_security_group(context, group_id, **group)

    @request_check(['max_rules_per_port'])
    def create_security_group_rule(self, context, group_id, rule):
        def check_ports(*args):
            limit = self.limits['max_rules_per_port']
            if limit and self._check_rule_count_per_port(
                    context, group_id) >= limit:
                return False
            return True

        return self._update_security_group_rules(
            context, group_id, rule, 'append',
            {(lambda x, y: x not in y):
             sg_ext.SecurityGroupRuleExists(id=group_id),
             check_ports:
             exceptions.DriverLimitReached(limit="rules per port")})

    def delete_security_group_rule(self, context, group_id, rule):
        return self._update_security_group_rules(
            context, group_id, rule, 'remove',
            {(lambda x, y: x in y):
             sg_ext.SecurityGroupRuleNotFound(id="with group_id %s" %
                                              group_id)})

    def _create_or_choose_lswitch(self, context, network_id):
        switches = self._lswitch_status_query(context, network_id)
        switch = self._lswitch_select_open(context, network_id=network_id,
                                           switches=switches)
        if switch:
            LOG.debug("Found open switch %s" % switch)
            return switch

        switch_details = self._get_network_details(context, network_id,
                                                   switches)
        if not switch_details:
            raise exceptions.BadNVPState(net_id=network_id)

        return self._lswitch_create(context, network_id=network_id,
                                    **switch_details)

    def _lswitch_status_query(self, context, network_id):
        query = self._lswitches_for_network(context, network_id)
        query.relations("LogicalSwitchStatus")
        results = query.results()
        LOG.debug("Query results: %s" % results)
        return results

    def _lswitch_select_open(self, context, switches=None, **kwargs):
        """Selects an open lswitch for a network. Note that it does not select
        the most full switch, but merely one with ports available.
        """
        if switches is not None:
            for res in switches["results"]:
                count = res["_relations"]["LogicalSwitchStatus"]["lport_count"]
                if self.limits['max_ports_per_switch'] == 0 or \
                        count < self.limits['max_ports_per_switch']:
                    return res["uuid"]
        return None

    def _lswitch_delete(self, context, lswitch_uuid):
        connection = self.get_connection()
        LOG.debug("Deleting lswitch %s" % lswitch_uuid)
        connection.lswitch(lswitch_uuid).delete()

    def _config_provider_attrs(self, connection, switch, phys_net,
                               net_type, segment_id):
        if not (phys_net or net_type):
            return
        if not phys_net and net_type:
            raise exceptions.ProvidernetParamError(
                msg="provider:physical_network parameter required")
        if phys_net and not net_type:
            raise exceptions.ProvidernetParamError(
                msg="provider:network_type parameter required")
        if not net_type in ("bridge", "vlan") and segment_id:
            raise exceptions.SegmentIdUnsupported(net_type=net_type)
        if net_type == "vlan" and not segment_id:
            raise exceptions.SegmentIdRequired(net_type=net_type)

        phys_type = physical_net_type_map.get(net_type.lower())
        if not phys_type:
            raise exceptions.InvalidPhysicalNetworkType(net_type=net_type)

        tz_query = connection.transportzone(phys_net).query()
        transport_zone = tz_query.results()

        if transport_zone["result_count"] == 0:
            raise exceptions.PhysicalNetworkNotFound(phys_net=phys_net)
        switch.transport_zone(zone_uuid=phys_net,
                              transport_type=phys_type,
                              vlan_id=segment_id)

    def _lswitch_create(self, context, network_name=None, tags=None,
                        network_id=None, phys_net=None,
                        phys_type=None, segment_id=None,
                        **kwargs):
        # NOTE(mdietz): physical net uuid maps to the transport zone uuid
        # physical net type maps to the transport/connector type
        # if type maps to 'bridge', then segment_id, which maps
        # to vlan_id, is conditionally provided
        LOG.debug("Creating new lswitch for %s network %s" %
                 (context.tenant_id, network_name))

        tenant_id = context.tenant_id
        connection = self.get_connection()

        switch = connection.lswitch()
        if network_name is None:
            network_name = network_id
        switch.display_name(network_name)
        tags = tags or []
        tags.append({"tag": tenant_id, "scope": "os_tid"})
        if network_id:
            tags.append({"tag": network_id, "scope": "quantum_net_id"})
        switch.tags(tags)
        LOG.debug("Creating lswitch for network %s" % network_id)

        # When connecting to public or snet, we need switches that are
        # connected to their respective public/private transport zones
        # using a "bridge" connector. Public uses no VLAN, whereas private
        # uses VLAN 122 in netdev. Probably need this to be configurable
        self._config_provider_attrs(connection, switch, phys_net, phys_type,
                                    segment_id)
        res = switch.create()
        return res["uuid"]

    def _lswitches_for_network(self, context, network_id):
        connection = self.get_connection()
        query = connection.lswitch().query()
        query.tagscopes(['os_tid', 'quantum_net_id'])
        query.tags([context.tenant_id, network_id])
        return query

    def _lswitch_from_port(self, context, port_id):
        connection = self.get_connection()
        query = connection.lswitch_port("*").query()
        query.relations("LogicalSwitchConfig")
        query.uuid(port_id)
        port = query.results()
        if port['result_count'] > 1:
            raise Exception("Could not identify lswitch for port %s" % port_id)
        if port['result_count'] < 1:
            raise Exception("No lswitch found for port %s" % port_id)
        return port['results'][0]["_relations"]["LogicalSwitchConfig"]["uuid"]

    def _get_security_group(self, context, group_id):
        connection = self.get_connection()
        query = connection.securityprofile().query()
        query.tagscopes(['os_tid', 'quantum_group_id'])
        query.tags([context.tenant_id, group_id])
        query = query.results()
        if query['result_count'] != 1:
            raise sg_ext.SecurityGroupNotFound(id=group_id)
        return query['results'][0]

    def _get_security_group_id(self, context, group_id):
        return self._get_security_group(context, group_id)['uuid']

    def _get_security_group_rule_object(self, context, rule):
        ethertype = rule.get('ethertype', None)
        rule_clone = {}

        ip_prefix = rule.get('remote_ip_prefix', None)
        if ip_prefix:
            rule_clone['ip_prefix'] = ip_prefix
        profile_uuid = rule.get('remote_group_id', None)
        if profile_uuid:
            rule_clone['profile_uuid'] = profile_uuid
        for key in ['protocol', 'port_range_min', 'port_range_max']:
            if rule.get(key):
                rule_clone[key] = rule[key]

        connection = self.get_connection()
        secrule = connection.securityrule(ethertype, **rule_clone)

        direction = rule.get('direction', '')
        if direction not in ['ingress', 'egress']:
            raise AttributeError(
                "Direction not specified as 'ingress' or 'egress'.")
        return (direction, secrule)

    def _check_rule_count_per_port(self, context, group_id):
        connection = self.get_connection()
        ports = connection.lswitch_port("*").query().security_profile_uuid(
            self._get_security_group_id(
                context, group_id)).results().get('results', [])
        groups = set(group for port in ports for
                     group in port.get('security_profiles', []))
        return self._check_rule_count_for_groups(
            context,
            (connection.securityprofile(group).read() for group in groups))

    def _check_rule_count_for_groups(self, context, groups):
        return sum(len(group['logical_port_ingress_rules']) +
                   len(group['logical_port_egress_rules'])
                   for group in groups)

    @request_check(['max_rules_per_port'])
    def _get_security_groups_for_port(self, context, groups):
        limit = self.limits['max_rules_per_port']
        if (limit is not False and
            self._check_rule_count_for_groups(
                context,
                (self._get_security_group(context, g) for g in groups))
                > limit):
            raise exceptions.DriverLimitReached(limit="rules per port")

        return [self._get_security_group(context, group)['uuid']
                for group in groups]
