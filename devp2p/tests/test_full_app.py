import pytest
import os
import time
from devp2p import app_helper
from devp2p.examples.full_app import Token, ExampleService, ExampleProtocol, ExampleApp
import gevent


class ExampleServiceIncCounter(ExampleService):
    def __init__(self, app):
        super(ExampleServiceIncCounter, self).__init__(app)
        self.collected = set()
        self.broadcasted = set()
        self.is_stopping = False
        gevent.spawn_later(0.5, self.tick)

    def on_wire_protocol_start(self, proto):
        assert isinstance(proto, self.wire_protocol)
        my_version = self.config['client_version_string']
        my_peers = self.app.services.peermanager.peers
        assert my_peers

        self.log('----------------------------------')
        self.log('on_wire_protocol_start', proto=proto, my_peers=my_peers)

        # check the peers is not connected to self
        for p in my_peers:
            assert p.remote_client_version != my_version

        # check the peers is connected to distinct nodes
        my_peers_with_hello_received = filter(lambda p: p.remote_client_version != '', my_peers)
        versions = map(lambda p: p.remote_client_version, my_peers_with_hello_received)
        self.log('versions', versions=versions)
        assert len(set(versions)) == len(versions)

        proto.receive_token_callbacks.append(self.on_receive_token)

        # check if number of peers that received hello is equal to number of min_peers
        if self.config['p2p']['min_peers'] == len(my_peers_with_hello_received):
            self.testdriver.NODES_PASSED_SETUP.add(my_version)
            if len(self.testdriver.NODES_PASSED_SETUP) == self.testdriver.NUM_NODES:
                self.send_synchro_token()

    def on_receive_token(self, proto, token):
        assert isinstance(token, Token)
        assert isinstance(proto, self.wire_protocol)
        self.log('----------------------------------')
        self.log('on_receive token {}'.format(token.counter),
                 collected=len(self.collected), broadcasted=len(self.broadcasted))

        assert token.counter not in self.collected

        # NODE0 must send first token to make algorithm work
        if not self.collected and not self.broadcasted and token.counter == 0:
            if self.config['node_num'] == 0:
                self.log("send initial token to the wire.")
                self.try_send_token()
            else:
                self.send_synchro_token()
            return

        if token.counter == 0:
            return

        self.collected.add(token.counter)
        self.log('collected token {}'.format(token.counter))

        if token.counter >= self.testdriver.COUNTER_LIMIT:
            self.stop_test()
            return

        self.try_send_token()

    def send_synchro_token(self):
        self.log("send synchronization token")
        self.broadcast(Token(counter=0, sender=self.address))

    def try_send_token(self):
        counter = 0 if not self.collected else max(self.collected)
        turn = counter % self.config['num_nodes']
        if turn != self.config['node_num']:
            return
        if counter+1 in self.broadcasted:
            return
        self.broadcasted.add(counter+1)
        token = Token(counter=counter+1, sender=self.address)
        self.log('sending token {}'.format(counter+1), token=token)
        self.broadcast(token)
        if counter+1 == self.testdriver.COUNTER_LIMIT:
            self.stop_test()

    def stop_test(self):
        if not self.is_stopping:
            self.log("COUNTER LIMIT REACHED. STOP THE APP")
            self.is_stopping = True
            # defer until all broadcast arrive
            gevent.spawn_later(2.0, self.assert_collected)

    def assert_collected(self):
        self.log("ASSERT", broadcasted=len(self.broadcasted), collected=len(self.collected))
        assert len(self.collected) > len(self.broadcasted)

        for turn in xrange(1, self.testdriver.COUNTER_LIMIT):
            if (turn-1) % self.testdriver.NUM_NODES == self.config['node_num']:
                assert turn in self.broadcasted
            else:
                assert turn in self.collected

        self.testdriver.NODES_PASSED_INC_COUNTER.add(self.config['node_num'])

    def tick(self):
        if len(self.testdriver.NODES_PASSED_INC_COUNTER) == self.testdriver.NUM_NODES:
            self.app.stop()
            return
        gevent.spawn_later(0.5, self.tick)


# xfail until issue 'error: [Errno 98] Address already in use' is not fixed
@pytest.mark.xfail
@pytest.mark.parametrize('num_nodes', [3, 6])
class TestFullApp:
    @pytest.mark.timeout(30)
    def test_inc_counter_app(self, num_nodes):
        class TestDriver(object):
            NUM_NODES = num_nodes
            COUNTER_LIMIT = 1024
            NODES_PASSED_SETUP = set()
            NODES_PASSED_INC_COUNTER = set()

        ExampleServiceIncCounter.testdriver = TestDriver()

        app_helper.run(ExampleApp, ExampleServiceIncCounter,
                       num_nodes=num_nodes, min_peers=num_nodes-1, max_peers=num_nodes-1)


if __name__ == "__main__":
    import devp2p.slogging as slogging
    slogging.configure(config_string=':debug,p2p:info')
    log = slogging.get_logger('app')
    TestFullAppIncCounter().test_full_app(3)
    TestFullAppIncCounter().test_full_app(6)