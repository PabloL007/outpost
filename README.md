# Outpost

![Build status](https://img.shields.io/docker/build/pablol007/outpost.svg)
![Docker pulls](https://img.shields.io/docker/pulls/pablol007/outpost.svg)

Welcome to the outpost repo! This is a simple service that obtains active connection information from running docker
containers and exposes it through a rest API.

## Example
The following is the output of running outpost on a host along with Zookeeper, Kafka and a Kafka console consumer:

```json
[
  {
    "name": "/kafka-console-consumer",
    "artefact": "wurstmeister/kafka:2.11-0.10.2.1",
    "listening": [],
    "established": [
      {
        "address": "192.168.56.101",
        "port": 9092
      },
      {
        "address": "192.168.56.101",
        "port": 9092
      },
      {
        "address": "192.168.56.101",
        "port": 9092
      }
    ]
  },
  {
    "name": "/kafka",
    "artefact": "wurstmeister/kafka:2.11-0.10.2.1",
    "listening": [
      {
        "address": "192.168.56.101",
        "port": 9092
      }
    ],
    "established": [
      {
        "address": "172.17.0.2",
        "port": 39534
      },
      {
        "address": "172.17.0.2",
        "port": 39536
      },
      {
        "address": "192.168.56.101",
        "port": 9092
      },
      {
        "address": "192.168.56.101",
        "port": 38000
      },
      {
        "address": "172.17.0.2",
        "port": 39532
      },
      {
        "address": "192.168.56.101",
        "port": 2181
      }
    ]
  },
  {
    "name": "/outpost",
    "artefact": "outpost",
    "listening": [
      {
        "address": "192.168.56.101",
        "port": 9057
      }
    ],
    "established": [
      {
        "address": "192.168.56.102",
        "port": 52495
      }
    ]
  },
  {
    "name": "/zookeeper",
    "artefact": "zookeeper:3.5",
    "listening": [
      {
        "address": "10.0.2.101",
        "port": 2181
      },
      {
        "address": "192.168.56.101",
        "port": 2181
      }
    ],
    "established": []
  }
]
```

Notes:

- Zookeeper isn't showing any established connections because it's running on the host and it's inode list couldn't be
obtained. When outpost tried to analyze it the following was written to the log:

`[WARNING] Unable to obtain inodes for the container's (6bc66590d22ccd3fab2cad1c4c81f739db21808ed6ff9ed00d8698d0bf624b0b) main process. Some connections will be omitted
to preserve accuracy`

## Running
To get started just modify the following docker run command:

```shell
 docker run -d  \
   -p 9057:9057 \
   -v /var/run/docker.sock:/var/run/docker.sock \
   -e "OUTPOST_INTERFACES=10.0.2.101,192.168.56.101" \
   --name outpost pablol007/outpost:0.1.1
```

The following variables can be used for configuration:

- `OUTPOST_INTERFACES`: As the proc filesystem can't be easily used to obtain the host interfaces' addresses, for now,
the workaround is to manually pass a comma separated list of IPs. This allows for determining what 'listening on all 
interfaces' actually means for clients. By default `0.0.0.0` will be used (if you want to use this for mapping
connections, you'll get much better results by providing the list)

- `LOG_LEVEL`: The logging level of both gunicorn and the app itself. `INFO` will be used by default, `DEBUG` shows some
 per container information that can help troubleshoot why a specific container's connections aren't being picked up
 correctly.

- `WORKERS`: Used to override the number of gevent workers. The default is calculated like so:
`min(10, (cpu_cores * 2) + 1)`

## How it works
Full disclosure, this service will execute the following commands on all running containers when the http endpoint is
called:

- (if the container is running on the host network) `sh -c 'ls -l /proc/1/fd 2> /dev/null | grep socket | sed -r "s/.+socket:\[([0-9]+)\]/\1/g"'`:
The problem with running on the host network is that the files in /proc/net will actually be the host's, which makes it
harder to determine which connections actually belong to the container. To work around this, this line gets the list of
inodes for the main process in the docker so that it can be used to filter out other processes' connections.

- `cat /proc/net/tcp`: To actually read the active connections (this is where netstat gets it's info).

- `cat /proc/net/tcp6`: Even though, at this point, outpost only officially supports tcp ipv4 connections, sometimes
ipv4 addresses will get mapped into the ipv6 space (even if clients don't actually use these addresses), so reading this
file as well will complete the picture.

Now, a valid question at this point is if there is a way to get this information without using the docker exec API. The
problem at this time is that the docker cp API can't be used to stream the contents of files in the proc filesystem.
Still, the objective of this project is to interfere as little as possible with the containers it's monitoring so
investigation into alternatives will continue (suggestions through github issues are welcome as well).

## Mapping and monitoring
By deploying one Outpost instance per docker host, another service can poll their endpoints, combine the outputs and
(matching established against listening connections) map links between containers. 