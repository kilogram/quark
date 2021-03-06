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

import netaddr
from neutron.openstack.common import log as logging

from quark.db import api as db_api
from quark import exceptions as quark_exceptions
from quark import plugin_views as v

LOG = logging.getLogger("neutron.quark")


def _to_mac_range(val):
    cidr_parts = val.split("/")
    prefix = cidr_parts[0]

    #FIXME(anyone): replace is slow, but this doesn't really
    #               get called ever. Fix maybe?
    prefix = prefix.replace(':', '')
    prefix = prefix.replace('-', '')
    prefix_length = len(prefix)
    if prefix_length < 6 or prefix_length > 10:
        raise quark_exceptions.InvalidMacAddressRange(cidr=val)

    diff = 12 - len(prefix)
    if len(cidr_parts) > 1:
        mask = int(cidr_parts[1])
    else:
        mask = 48 - diff * 4
    mask_size = 1 << (48 - mask)
    prefix = "%s%s" % (prefix, "0" * diff)
    try:
        cidr = "%s/%s" % (str(netaddr.EUI(prefix)).replace("-", ":"), mask)
    except netaddr.AddrFormatError:
        raise quark_exceptions.InvalidMacAddressRange(cidr=val)
    prefix_int = int(prefix, base=16)
    return cidr, prefix_int, prefix_int + mask_size


def get_mac_address_range(context, id, fields=None):
    """Retrieve a mac_address_range.

    : param context: neutron api request context
    : param id: UUID representing the network to fetch.
    : param fields: a list of strings that are valid keys in a
        network dictionary as listed in the RESOURCE_ATTRIBUTE_MAP
        object in neutron/api/v2/attributes.py. Only these fields
        will be returned.
    """
    LOG.info("get_mac_address_range %s for tenant %s fields %s" %
            (id, context.tenant_id, fields))

    mac_address_range = db_api.mac_address_range_find(
        context, id=id, scope=db_api.ONE)

    if not mac_address_range:
        raise quark_exceptions.MacAddressRangeNotFound(
            mac_address_range_id=id)
    return v._make_mac_range_dict(mac_address_range)


def get_mac_address_ranges(context):
    LOG.info("get_mac_address_ranges for tenant %s" % context.tenant_id)
    ranges = db_api.mac_address_range_find(context)
    return [v._make_mac_range_dict(m) for m in ranges]


def create_mac_address_range(context, mac_range):
    LOG.info("create_mac_address_range for tenant %s" % context.tenant_id)
    cidr = mac_range["mac_address_range"]["cidr"]
    cidr, first_address, last_address = _to_mac_range(cidr)
    new_range = db_api.mac_address_range_create(
        context, cidr=cidr, first_address=first_address,
        last_address=last_address, next_auto_assign_mac=first_address)
    return v._make_mac_range_dict(new_range)


def _delete_mac_address_range(context, mac_address_range):
    if mac_address_range.allocated_macs:
        raise quark_exceptions.MacAddressRangeInUse(
            mac_address_range_id=mac_address_range["id"])
    db_api.mac_address_range_delete(context, mac_address_range)


def delete_mac_address_range(context, id):
    """Delete a mac_address_range.

    : param context: neutron api request context
    : param id: UUID representing the mac_address_range to delete.
    """
    LOG.info("delete_mac_address_range %s for tenant %s" %
             (id, context.tenant_id))
    mar = db_api.mac_address_range_find(context, id=id, scope=db_api.ONE)
    if not mar:
        raise quark_exceptions.MacAddressRangeNotFound(
            mac_address_range_id=id)
    _delete_mac_address_range(context, mar)
