from app import app
from app import utils

import logging
import json
import os
import docker

interfaces = os.environ.get('OUTPOST_INTERFACES', '0.0.0.0').split(',')

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

log = app.logger


@app.route('/')
@app.route('/index')
def index():
    napps = []
    # Initialize connection to the docker socket
    client = docker.APIClient(base_url='unix://var/run/docker.sock')
    # Get the list of running containers
    containers = client.containers()
    log.info('Retrieving connections for ' + str(len(containers)) + ' container/s')
    for container in containers:
        log.debug('Gathering intel on "' + container['Id'] + '"')
        # Inspect it
        config = client.inspect_container(container['Id'])
        name = config['Name']
        artefact = config['Config']['Image']
        # Determine if it's on the host network
        host = config['HostConfig']['NetworkMode'] == 'host'
        # Get exposed/mapped ports
        ports = {}
        for key, port in config['HostConfig']['PortBindings'].items():
            host_ip = '0.0.0.0' if port[0]['HostIp'] == '' else port[0]['HostIp']
            ports.update({int(port[0]['HostPort']): host_ip})
        log.debug('Port Bindings: ' + json.dumps(ports))
        # Get connections
        raw_connections = utils.get_container_connections(client, container['Id'], host, list(ports.keys()), log)
        # Transform all interface listeners into individual listeners for each interface and convert mapped ipv4
        # addresses in the listening list
        fan_out = []
        for connection in raw_connections['listening']:
            address = connection['address'] if host else ports[connection['port']]
            if address == '00000000:00000000:00000000:00000000' or address == '0.0.0.0':
                for interface in interfaces:
                    fan_out += [{'address': interface, 'port': connection['port']}]
                continue
            elif address.startswith('00000000:00000000:0000FFFF:'):
                fan_out += [{'address': utils.mapped_ipv6_to_ipv4(address.split(':')[-1]), 'port': connection['port']}]
            else:
                fan_out += [{'address': address, 'port': connection['port']}]
        raw_connections['listening'] = fan_out
        # Convert mapped ipv4 addresses in the established list
        fan_out = []
        for connection in raw_connections['established']:
            if connection['address'].startswith('00000000:00000000:0000FFFF:'):
                fan_out += [{'address': utils.mapped_ipv6_to_ipv4(connection['address'].split(':')[-1]), 'port': connection['port']}]
            else:
                fan_out += [connection]
        raw_connections['established'] = fan_out
        intel = {'name': name, 'artefact': artefact, 'listening': raw_connections['listening'], 'established': raw_connections['established']}
        log.debug('Result: ' + json.dumps(intel))
        napps += [intel]
    client.close()
    return json.dumps(napps)
