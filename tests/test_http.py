# Copyright 2012 OpenStack Foundation
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
import json

from keystoneclient.auth import token_endpoint
from keystoneclient import session
import requests
from requests_mock.contrib import fixture
import six
from six.moves.urllib import parse
from testscenarios import load_tests_apply_scenarios as load_tests  # noqa
import testtools
import types

import glanceclient
from glanceclient.common import http
from glanceclient.common import https
from glanceclient import exc
from tests import utils


class TestClient(testtools.TestCase):

    scenarios = [
        ('httpclient', {'create_client': '_create_http_client'}),
        ('session', {'create_client': '_create_session_client'})
    ]

    def _create_http_client(self):
        return http.HTTPClient(self.endpoint, token=self.token)

    def _create_session_client(self):
        auth = token_endpoint.Token(self.endpoint, self.token)
        sess = session.Session(auth=auth)
        return http.SessionClient(sess)

    def setUp(self):
        super(TestClient, self).setUp()
        self.mock = self.useFixture(fixture.Fixture())

        self.endpoint = 'http://example.com:9292'
        self.token = u'abc123'

        self.client = getattr(self, self.create_client)()

    def test_identity_headers_and_token(self):
        identity_headers = {
            'X-Auth-Token': 'auth_token',
            'X-User-Id': 'user',
            'X-Tenant-Id': 'tenant',
            'X-Roles': 'roles',
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'service_catalog',
        }
        #with token
        kwargs = {'token': u'fake-token',
                  'identity_headers': identity_headers}
        http_client_object = http.HTTPClient(self.endpoint, **kwargs)
        self.assertEqual('auth_token', http_client_object.auth_token)
        self.assertTrue(http_client_object.identity_headers.
                        get('X-Auth-Token') is None)

    def test_identity_headers_and_no_token_in_header(self):
        identity_headers = {
            'X-User-Id': 'user',
            'X-Tenant-Id': 'tenant',
            'X-Roles': 'roles',
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'service_catalog',
        }
        #without X-Auth-Token in identity headers
        kwargs = {'token': u'fake-token',
                  'identity_headers': identity_headers}
        http_client_object = http.HTTPClient(self.endpoint, **kwargs)
        self.assertEqual(u'fake-token', http_client_object.auth_token)
        self.assertTrue(http_client_object.identity_headers.
                        get('X-Auth-Token') is None)

    def test_identity_headers_and_no_token_in_session_header(self):
        # Tests that if token or X-Auth-Token are not provided in the kwargs
        # when creating the http client, the session headers don't contain
        # the X-Auth-Token key.
        identity_headers = {
            'X-User-Id': 'user',
            'X-Tenant-Id': 'tenant',
            'X-Roles': 'roles',
            'X-Identity-Status': 'Confirmed',
            'X-Service-Catalog': 'service_catalog',
        }
        kwargs = {'identity_headers': identity_headers}
        http_client_object = http.HTTPClient(self.endpoint, **kwargs)
        self.assertIsNone(http_client_object.auth_token)
        self.assertNotIn('X-Auth-Token', http_client_object.session.headers)

    def test_identity_headers_are_passed(self):
        # Tests that if token or X-Auth-Token are not provided in the kwargs
        # when creating the http client, the session headers don't contain
        # the X-Auth-Token key.
        identity_headers = {
            'X-User-Id': b'user',
            'X-Tenant-Id': b'tenant',
            'X-Roles': b'roles',
            'X-Identity-Status': b'Confirmed',
            'X-Service-Catalog': b'service_catalog',
        }
        kwargs = {'identity_headers': identity_headers}
        http_client = http.HTTPClient(self.endpoint, **kwargs)

        path = '/v1/images/my-image'
        self.mock.get(self.endpoint + path)
        http_client.get(path)

        headers = self.mock.last_request.headers
        for k, v in six.iteritems(identity_headers):
            self.assertEqual(v, headers[k])

    def test_connection_refused(self):
        """
        Should receive a CommunicationError if connection refused.
        And the error should list the host and port that refused the
        connection
        """
        def cb(request, context):
            raise requests.exceptions.ConnectionError()

        path = '/v1/images/detail?limit=20'
        self.mock.get(self.endpoint + path, text=cb)

        comm_err = self.assertRaises(glanceclient.exc.CommunicationError,
                                     self.client.get,
                                     '/v1/images/detail?limit=20')

        self.assertIn(self.endpoint, comm_err.message)

    def test_http_encoding(self):
        path = '/v1/images/detail'
        text = 'Ok'
        self.mock.get(self.endpoint + path, text=text,
                      headers={"Content-Type": "text/plain"})

        headers = {"test": u'ni\xf1o'}
        resp, body = self.client.get(path, headers=headers)
        self.assertEqual(text, resp.text)

    def test_headers_encoding(self):
        if not hasattr(self.client, 'encode_headers'):
            self.skipTest('Cannot do header encoding check on SessionClient')

        value = u'ni\xf1o'
        headers = {"test": value, "none-val": None}
        encoded = self.client.encode_headers(headers)
        self.assertEqual(b"ni\xc3\xb1o", encoded[b"test"])
        self.assertNotIn("none-val", encoded)

    def test_raw_request(self):
        " Verify the path being used for HTTP requests reflects accurately. "
        headers = {"Content-Type": "text/plain"}
        text = 'Ok'
        path = '/v1/images/detail'

        self.mock.get(self.endpoint + path, text=text, headers=headers)

        resp, body = self.client.get('/v1/images/detail', headers=headers)
        self.assertEqual(headers, resp.headers)
        self.assertEqual(text, resp.text)

    def test_parse_endpoint(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        actual = test_client.parse_endpoint(endpoint)
        expected = parse.SplitResult(scheme='http',
                                     netloc='example.com:9292', path='',
                                     query='', fragment='')
        self.assertEqual(expected, actual)

    def test_get_connections_kwargs_http(self):
        endpoint = 'http://example.com:9292'
        test_client = http.HTTPClient(endpoint, token=u'adc123')
        self.assertEqual(test_client.timeout, 600.0)

    def test_http_chunked_request(self):
        text = "Ok"
        data = six.StringIO(text)
        path = '/v1/images/'
        self.mock.post(self.endpoint + path, text=text)

        headers = {"test": u'chunked_request'}
        resp, body = self.client.post(path, headers=headers, data=data)
        self.assertIsInstance(self.mock.last_request.body, types.GeneratorType)
        self.assertEqual(text, resp.text)

    def test_http_json(self):
        data = {"test": "json_request"}
        path = '/v1/images'
        text = 'OK'
        self.mock.post(self.endpoint + path, text=text)

        headers = {"test": u'chunked_request'}
        resp, body = self.client.post(path, headers=headers, data=data)

        self.assertEqual(text, resp.text)
        self.assertIsInstance(self.mock.last_request.body, six.string_types)
        self.assertEqual(data, json.loads(self.mock.last_request.body))

    def test_http_chunked_response(self):
        data = "TEST"
        path = '/v1/images/'
        self.mock.get(self.endpoint + path, body=six.StringIO(data),
                      headers={"Content-Type": "application/octet-stream"})

        resp, body = self.client.get(path)
        self.assertTrue(isinstance(body, types.GeneratorType))
        self.assertEqual([data], list(body))

    def test_log_http_response_with_non_ascii_char(self):
        if not hasattr(self.client, 'log_http_response'):
            self.skipTest('Cannot do log checking on SessionClient')

        try:
            response = 'Ok'
            headers = {"Content-Type": "text/plain",
                       "test": "value1\xa5\xa6"}
            fake = utils.FakeResponse(headers, six.StringIO(response))
            self.client.log_http_response(fake)
        except UnicodeDecodeError as e:
            self.fail("Unexpected UnicodeDecodeError exception '%s'" % e)


class TestVerifiedHTTPSConnection(testtools.TestCase):
    """Test fixture for glanceclient.common.http.VerifiedHTTPSConnection."""

    def test_setcontext_unable_to_load_cacert(self):
        """Add this UT case with Bug#1265730."""
        self.assertRaises(exc.SSLConfigurationError,
                          https.VerifiedHTTPSConnection,
                          "127.0.0.1",
                          None,
                          None,
                          None,
                          "gx_cacert",
                          None,
                          False,
                          True)
