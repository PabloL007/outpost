from logging import Logger
from docker import APIClient

import json


def mapped_ipv6_to_ipv4(hex):
    """
    For converting ipv4 addresses mapped to ipv6 back to ipv4
    :param hex: ipv6 address without the '00000000:00000000:0000FFFF:' prefix
    :return: String containing the ipv4 address
    """
    grouped = [hex[i:i + 2] for i in range(0, len(hex), 2)]
    return '.'.join(list(map(lambda x: str(int(x, 16)), grouped)))


def hex_to_ip(hex, ipv6):
    """
    For decoding addresses in /proc/net files into readable ipv4 and ipv6 strings
    :param hex: Encoded address
    :param ipv6: True if it's ipv6, False otherwise
    :return: A string with the decoded address
    """
    if ipv6:
        grouped = [hex[i:i + 8] for i in range(0, len(hex), 8)]
        grouped = map(lambda word: ''.join([word[i:i + 2] for i in range(0, len(word), 2)][::-1]), grouped)
        result = ':'.join(grouped)
    else:
        grouped = [hex[i:i + 2] for i in range(0, len(hex), 2)]
        grouped.reverse()
        result = '.'.join(list(map(lambda x: str(int(x, 16)), grouped)))
    return result


def hex_to_tcp_state(hex):
    """
    For converting tcp state hex codes to human readable strings.
    :param hex: TCP status hex code (as a string)
    :return: String containing the human readable state
    """
    states = {
        '01': 'TCP_ESTABLISHED',
        '02': 'TCP_SYN_SENT',
        '03': 'TCP_SYN_RECV',
        '04': 'TCP_FIN_WAIT1',
        '05': 'TCP_FIN_WAIT2',
        '06': 'TCP_TIME_WAIT',
        '07': 'TCP_CLOSE',
        '08': 'TCP_CLOSE_WAIT',
        '09': 'TCP_LAST_ACK',
        '0A': 'TCP_LISTEN',
        '0B': 'TCP_CLOSING'
    }
    return states[hex]


def get_connections(lines: enumerate, host: bool, inodes: list, ipv6: bool = False):
    """
    For parsing /proc/net/tcp* files.
    :param lines: Enumeration of lines
    :param host: True if the file belongs to the host, False otherwise
    :param inodes: List of inodes owned by the process so connections can be filtered when the file comes from the host
    :param ipv6: True if addresses in the file are ipv6, False otherwise
    :return: JSON with listening and established connection lists
    """
    connections = {'listening': [], 'established': []}
    for cnt, line in lines:
        if cnt == 0 or line == '':
            continue
        columns = line.split(' ')
        columns = list(filter(lambda item: item != '', columns))
        state = hex_to_tcp_state(columns[3])
        if state == 'TCP_ESTABLISHED':
            if host and columns[9] not in inodes:
                continue
            remote_address = hex_to_ip(columns[2].split(':')[0], ipv6)
            remote_port = int(columns[2].split(':')[1], 16)
            connections['established'] += [{'address': remote_address, 'port': remote_port}]
        elif state == 'TCP_LISTEN':
            if host and len(inodes) > 0 and columns[9] not in inodes:
                continue
            local_address = hex_to_ip(columns[1].split(':')[0], ipv6)
            local_port = int(columns[1].split(':')[1], 16)
            connections['listening'] += [{'address': local_address, 'port': local_port}]
    return connections


def get_container_connections(client: APIClient, id: str, host: bool, ports: list, log: Logger):
    """
    Docker container specific wrapper for the get_connections function.
    :param client: Docker APIClient
    :param id: Container id string
    :param host: True if the container is running on the host network, False otherwise
    :param ports: List of published ports for the container
    :param log: Logger
    :return: JSON with listening and established connection lists
    """
    inodes = []
    if host:
        # Try to get inodes for the main process
        session = client.exec_create(id, r'''
        sh -c 'ls -l /proc/1/fd 2> /dev/null | grep socket | sed -r "s/.+socket:\[([0-9]+)\]/\1/g"'
        ''')
        inodes = client.exec_start(exec_id=session['Id'])
        inodes = inodes.decode('utf-8').split('\n')
        inodes = list(filter(lambda inode: inode != '', inodes))
        log.debug('inodes: ' + json.dumps(inodes))
        if len(inodes) == 0:
            log.warning(
                'Unable to obtain inodes for the container\'s (' + id +
                ') main process. Some connections will be omitted to preserve accuracy')

    session = client.exec_create(id, 'cat /proc/net/tcp')
    tcp = client.exec_start(exec_id=session['Id'])
    part1 = get_connections(enumerate(tcp.decode('utf-8').split('\n')), host, inodes)

    session = client.exec_create(id, 'cat /proc/net/tcp6')
    tcp6 = client.exec_start(exec_id=session['Id'])
    part2 = get_connections(enumerate(tcp6.decode('utf-8').split('\n')), host, inodes, True)

    result = {
        'listening': part1['listening'] + part2['listening'],
        'established': part1['established'] + part2['established']
    }

    if not host or (host and len(inodes) == 0):
        # Filter out listening connections on unmapped ports (either because they would be unreachable from the host or
        # because we have no way of knowing if they belong to the container or not)
        result['listening'] = list(
            filter(lambda connection: connection['port'] in ports, result['listening']))

    return result
