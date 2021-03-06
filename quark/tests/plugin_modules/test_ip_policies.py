# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
#  under the License.

import contextlib

import mock
import netaddr
from neutron.common import exceptions

from quark import exceptions as quark_exceptions
from quark.tests import test_quark_plugin


class TestQuarkGetIpPolicies(test_quark_plugin.TestQuarkPlugin):
    @contextlib.contextmanager
    def _stubs(self, ip_policy):
        db_mod = "quark.db.api"
        with mock.patch("%s.ip_policy_find" % db_mod) as ip_policy_find:
            ip_policy_find.return_value = ip_policy
            yield

    def test_get_ip_policy_not_found(self):
        with self._stubs(None):
            with self.assertRaises(quark_exceptions.IPPolicyNotFound):
                self.plugin.get_ip_policy(self.context, 1)

    def test_get_ip_policy(self):
        address = int(netaddr.IPAddress("1.1.1.1"))
        ip_policy = dict(
            id=1,
            subnet_id=1,
            network_id=2,
            exclude=[dict(address=address, prefix=24)])
        with self._stubs(ip_policy):
            resp = self.plugin.get_ip_policy(self.context, 1)
            self.assertEqual(len(resp.keys()), 4)
            self.assertEqual(resp["id"], 1)
            self.assertEqual(resp["subnet_id"], 1)
            self.assertEqual(resp["network_id"], 2)
            self.assertEqual(resp["exclude"], ["1.1.1.1/24"])

    def test_get_ip_policies(self):
        address = int(netaddr.IPAddress("1.1.1.1"))
        ip_policy = dict(
            id=1,
            subnet_id=1,
            network_id=2,
            exclude=[dict(address=address, prefix=24)])
        with self._stubs([ip_policy]):
            resp = self.plugin.get_ip_policies(self.context)
            self.assertEqual(len(resp), 1)
            resp = resp[0]
            self.assertEqual(len(resp.keys()), 4)
            self.assertEqual(resp["id"], 1)
            self.assertEqual(resp["subnet_id"], 1)
            self.assertEqual(resp["network_id"], 2)
            self.assertEqual(resp["exclude"], ["1.1.1.1/24"])


class TestQuarkCreateIpPolicies(test_quark_plugin.TestQuarkPlugin):
    @contextlib.contextmanager
    def _stubs(self, ip_policy, subnet=None, net=None):
        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.subnet_find" % db_mod),
            mock.patch("%s.network_find" % db_mod),
            mock.patch("%s.ip_policy_create" % db_mod),
        ) as (subnet_find, net_find, ip_policy_create):
            subnet_find.return_value = subnet
            net_find.return_value = net
            ip_policy_create.return_value = ip_policy
            yield ip_policy_create

    def test_create_ip_policy_invalid_body_missing_exclude(self):
        with self._stubs(None):
            with self.assertRaises(exceptions.BadRequest):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict()))

    def test_create_ip_policy_invalid_body_missing_netsubnet(self):
        with self._stubs(None):
            with self.assertRaises(exceptions.BadRequest):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(exclude=["1.1.1.1/24"])))

    def test_create_ip_policy_invalid_subnet(self):
        with self._stubs(None):
            with self.assertRaises(exceptions.SubnetNotFound):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(subnet_id=1,
                                   exclude=["1.1.1.1/24"])))

    def test_create_ip_policy_invalid_network(self):
        with self._stubs(None):
            with self.assertRaises(exceptions.NetworkNotFound):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(network_id=1,
                                   exclude=["1.1.1.1/24"])))

    def test_create_ip_policy_network_ip_policy_already_exists(self):
        with self._stubs(None, net=dict(id=1, ip_policy=dict(id=2))):
            with self.assertRaises(quark_exceptions.IPPolicyAlreadyExists):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(network_id=1,
                                   exclude=["1.1.1.1/24"])))

    def test_create_ip_policy_subnet_ip_policy_already_exists(self):
        with self._stubs(None, subnet=dict(id=1, ip_policy=dict(id=2))):
            with self.assertRaises(quark_exceptions.IPPolicyAlreadyExists):
                self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(subnet_id=1,
                                   exclude=["1.1.1.1/24"])))

    def test_create_ip_policy_network(self):
        ipp = dict(subnet_id=None, network_id=1,
                   exclude=[dict(address=int(netaddr.IPAddress("1.1.1.1")),
                                 prefix=24)])
        with self._stubs(ipp, net=dict(id=1, ip_policy=dict(id=2))):
            with self.assertRaises(quark_exceptions.IPPolicyAlreadyExists):
                resp = self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(network_id=1,
                                   exclude=["1.1.1.1/24"])))
                self.assertEqual(len(resp.keys()), 3)
                self.assertIsNone(resp["subnet_id"])
                self.assertEqual(resp["network_id"], 1)
                self.assertEqual(resp["exclude"], ["1.1.1.1/24"])

    def test_create_ip_policy_subnet(self):
        ipp = dict(subnet_id=1, network_id=None,
                   exclude=[dict(address=int(netaddr.IPAddress("1.1.1.1")),
                                 prefix=24)])
        with self._stubs(ipp, subnet=dict(id=1, ip_policy=dict(id=2))):
            with self.assertRaises(quark_exceptions.IPPolicyAlreadyExists):
                resp = self.plugin.create_ip_policy(self.context, dict(
                    ip_policy=dict(subnet_id=1,
                                   exclude=["1.1.1.1/24"])))
                self.assertEqual(len(resp.keys()), 3)
                self.assertEqual(resp["subnet_id"], 1)
                self.assertIsNone(resp["network_id"])
                self.assertEqual(resp["exclude"], ["1.1.1.1/24"])

    def test_create_ip_policy(self):
        ipp = dict(subnet_id=1, network_id=None, id=1,
                   exclude=[dict(address=int(netaddr.IPAddress("1.1.1.1")),
                                 prefix=24)])
        with self._stubs(ipp, subnet=dict(id=1, ip_policy=None)):
            resp = self.plugin.create_ip_policy(self.context, dict(
                ip_policy=dict(subnet_id=1,
                               exclude=["1.1.1.1/24"])))
            self.assertEqual(len(resp.keys()), 4)
            self.assertEqual(resp["subnet_id"], 1)
            self.assertIsNone(resp["network_id"])
            self.assertEqual(resp["exclude"], ["1.1.1.1/24"])


class TestQuarkDeleteIpPolicies(test_quark_plugin.TestQuarkPlugin):
    @contextlib.contextmanager
    def _stubs(self, ip_policy):
        db_mod = "quark.db.api"
        with contextlib.nested(
            mock.patch("%s.ip_policy_find" % db_mod),
            mock.patch("%s.ip_policy_delete" % db_mod),
        ) as (ip_policy_find, ip_policy_delete):
            ip_policy_find.return_value = ip_policy
            yield ip_policy_find, ip_policy_delete

    def test_delete_ip_policy_not_found(self):
        with self._stubs(None):
            with self.assertRaises(quark_exceptions.IPPolicyNotFound):
                self.plugin.delete_ip_policy(self.context, 1)

    def test_delete_ip_policy(self):
        address = int(netaddr.IPAddress("1.1.1.1"))
        ip_policy = dict(
            id=1,
            subnet_id=1,
            network_id=2,
            exclude=[dict(address=address, prefix=24)])
        with self._stubs(ip_policy) as (ip_policy_find, ip_policy_delete):
            self.plugin.delete_ip_policy(self.context, 1)
            self.assertEqual(ip_policy_find.call_count, 1)
            self.assertEqual(ip_policy_delete.call_count, 1)
