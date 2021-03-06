import os
import time
import struct
import platform
import subprocess
from fcntl import ioctl
from pyroute2.common import map_namespace
from pyroute2.common import ANCIENT
# from pyroute2.netlink import NLMSG_ERROR
from pyroute2.netlink import nla
from pyroute2.netlink import nlmsg
from pyroute2.netlink.rtnl.iw_event import iw_event

_ANCIENT_BARRIER = 0.3
_BONDING_MASTERS = '/sys/class/net/bonding_masters'
_BONDING_SLAVES = '/sys/class/net/%s/bonding/slaves'
_BRIDGE_MASTER = '/sys/class/net/%s/brport/bridge/ifindex'
_BONDING_MASTER = '/sys/class/net/%s/master/ifindex'
IFNAMSIZ = 16

TUNDEV = '/dev/net/tun'
arch = platform.machine()
if arch == 'x86_64':
    TUNSETIFF = 0x400454ca
    TUNSETPERSIST = 0x400454cb
    TUNSETOWNER = 0x400454cc
    TUNSETGROUP = 0x400454ce
elif arch == 'ppc64':
    TUNSETIFF = 0x800454ca
    TUNSETPERSIST = 0x800454cb
    TUNSETOWNER = 0x800454cc
    TUNSETGROUP = 0x800454ce
else:
    TUNSETIFF = None

##
#
# tuntap flags
#
IFT_TUN = 0x0001
IFT_TAP = 0x0002
IFT_NO_PI = 0x1000
IFT_ONE_QUEUE = 0x2000
IFT_VNET_HDR = 0x4000
IFT_TUN_EXCL = 0x8000
IFT_MULTI_QUEUE = 0x0100
IFT_ATTACH_QUEUE = 0x0200
IFT_DETACH_QUEUE = 0x0400
# read-only
IFT_PERSIST = 0x0800
IFT_NOFILTER = 0x1000

##
#
# normal flags
#
IFF_UP = 0x1  # interface is up
IFF_BROADCAST = 0x2  # broadcast address valid
IFF_DEBUG = 0x4  # turn on debugging
IFF_LOOPBACK = 0x8  # is a loopback net
IFF_POINTOPOINT = 0x10  # interface is has p-p link
IFF_NOTRAILERS = 0x20  # avoid use of trailers
IFF_RUNNING = 0x40  # interface RFC2863 OPER_UP
IFF_NOARP = 0x80  # no ARP protocol
IFF_PROMISC = 0x100  # receive all packets
IFF_ALLMULTI = 0x200  # receive all multicast packets
IFF_MASTER = 0x400  # master of a load balancer
IFF_SLAVE = 0x800  # slave of a load balancer
IFF_MULTICAST = 0x1000  # Supports multicast
IFF_PORTSEL = 0x2000  # can set media type
IFF_AUTOMEDIA = 0x4000  # auto media select active
IFF_DYNAMIC = 0x8000  # dialup device with changing addresses
IFF_LOWER_UP = 0x10000  # driver signals L1 up
IFF_DORMANT = 0x20000  # driver signals dormant
IFF_ECHO = 0x40000  # echo sent packets

(IFF_NAMES, IFF_VALUES) = map_namespace('IFF', globals())

IFF_MASK = IFF_UP |\
    IFF_DEBUG |\
    IFF_NOTRAILERS |\
    IFF_NOARP |\
    IFF_PROMISC |\
    IFF_ALLMULTI

IFF_VOLATILE = IFF_LOOPBACK |\
    IFF_POINTOPOINT |\
    IFF_BROADCAST |\
    IFF_ECHO |\
    IFF_MASTER |\
    IFF_SLAVE |\
    IFF_RUNNING |\
    IFF_LOWER_UP |\
    IFF_DORMANT

states = ('UNKNOWN',
          'NOTPRESENT',
          'DOWN',
          'LOWERLAYERDOWN',
          'TESTING',
          'DORMANT',
          'UP')
state_by_name = dict(((i[1], i[0]) for i in enumerate(states)))
state_by_code = dict(enumerate(states))
stats_names = ('rx_packets',
               'tx_packets',
               'rx_bytes',
               'tx_bytes',
               'rx_errors',
               'tx_errors',
               'rx_dropped',
               'tx_dropped',
               'multicast',
               'collisions',
               'rx_length_errors',
               'rx_over_errors',
               'rx_crc_errors',
               'rx_frame_errors',
               'rx_fifo_errors',
               'rx_missed_errors',
               'tx_aborted_errors',
               'tx_carrier_errors',
               'tx_fifo_errors',
               'tx_heartbeat_errors',
               'tx_window_errors',
               'rx_compressed',
               'tx_compressed')


class ifinfbase(object):
    '''
    Network interface message
    struct ifinfomsg {
        unsigned char  ifi_family; /* AF_UNSPEC */
        unsigned short ifi_type;   /* Device type */
        int            ifi_index;  /* Interface index */
        unsigned int   ifi_flags;  /* Device flags  */
        unsigned int   ifi_change; /* change mask */
    };
    '''
    prefix = 'IFLA_'

    fields = (('family', 'B'),
              ('__align', 'B'),
              ('ifi_type', 'H'),
              ('index', 'i'),
              ('flags', 'I'),
              ('change', 'I'))

    nla_map = (('IFLA_UNSPEC', 'none'),
               ('IFLA_ADDRESS', 'l2addr'),
               ('IFLA_BROADCAST', 'l2addr'),
               ('IFLA_IFNAME', 'asciiz'),
               ('IFLA_MTU', 'uint32'),
               ('IFLA_LINK', 'uint32'),
               ('IFLA_QDISC', 'asciiz'),
               ('IFLA_STATS', 'ifstats'),
               ('IFLA_COST', 'hex'),
               ('IFLA_PRIORITY', 'hex'),
               ('IFLA_MASTER', 'uint32'),
               ('IFLA_WIRELESS', 'wireless'),
               ('IFLA_PROTINFO', 'hex'),
               ('IFLA_TXQLEN', 'uint32'),
               ('IFLA_MAP', 'ifmap'),
               ('IFLA_WEIGHT', 'hex'),
               ('IFLA_OPERSTATE', 'state'),
               ('IFLA_LINKMODE', 'uint8'),
               ('IFLA_LINKINFO', 'ifinfo'),
               ('IFLA_NET_NS_PID', 'uint32'),
               ('IFLA_IFALIAS', 'hex'),
               ('IFLA_NUM_VF', 'uint32'),
               ('IFLA_VFINFO_LIST', 'hex'),
               ('IFLA_STATS64', 'ifstats64'),
               ('IFLA_VF_PORTS', 'hex'),
               ('IFLA_PORT_SELF', 'hex'),
               ('IFLA_AF_SPEC', 'af_spec'),
               ('IFLA_GROUP', 'uint32'),
               ('IFLA_NET_NS_FD', 'netns_fd'),
               ('IFLA_EXT_MASK', 'hex'),
               ('IFLA_PROMISCUITY', 'uint32'),
               ('IFLA_NUM_TX_QUEUES', 'uint32'),
               ('IFLA_NUM_RX_QUEUES', 'uint32'),
               ('IFLA_CARRIER', 'uint8'),
               ('IFLA_PHYS_PORT_ID', 'hex'),
               ('IFLA_CARRIER_CHANGES', 'uint32'))

    @staticmethod
    def flags2names(flags, mask=0xffffffff):
        ret = []
        for flag in IFF_VALUES:
            if (flag & mask & flags) == flag:
                ret.append(IFF_VALUES[flag])
        return ret

    @staticmethod
    def names2flags(flags):
        ret = 0
        mask = 0
        for flag in flags:
            if flag[0] == '!':
                flag = flag[1:]
            else:
                ret |= IFF_NAMES[flag]
            mask |= IFF_NAMES[flag]
        return (ret, mask)

    def encode(self):
        # convert flags
        if isinstance(self['flags'], (set, tuple, list)):
            self['flags'], self['change'] = self.names2flags(self['flags'])
        return super(ifinfbase, self).encode()

    class netns_fd(nla):
        fields = [('value', 'I')]
        netns_run_dir = '/var/run/netns'
        netns_fd = None

        def encode(self):
            self.close()
            #
            # There are two ways to specify netns
            #
            # 1. provide fd to an open file
            # 2. provide a file name
            #
            # In the first case, the value is passed to the kernel
            # as is. In the second case, the object opens appropriate
            # file from `self.netns_run_dir` and closes it upon
            # `__del__(self)`
            if isinstance(self.value, int):
                self['value'] = self.value
            else:
                self.netns_fd = os.open('%s/%s' % (self.netns_run_dir,
                                                   self.value), os.O_RDONLY)
                self['value'] = self.netns_fd
            nla.encode(self)

        def __del__(self):
            self.close()

        def close(self):
            if self.netns_fd is not None:
                os.close(self.netns_fd)

    class wireless(iw_event):
        pass

    class state(nla):
        fields = (('value', 'B'), )

        def encode(self):
            self['value'] = state_by_name[self.value]
            nla.encode(self)

        def decode(self):
            nla.decode(self)
            self.value = state_by_code[self['value']]

    class ifstats(nla):
        fields = [(i, 'I') for i in stats_names]

    class ifstats64(nla):
        fields = [(i, 'Q') for i in stats_names]

    class ifmap(nla):
        fields = (('mem_start', 'Q'),
                  ('mem_end', 'Q'),
                  ('base_addr', 'Q'),
                  ('irq', 'H'),
                  ('dma', 'B'),
                  ('port', 'B'))

    class ifinfo(nla):
        nla_map = (('IFLA_INFO_UNSPEC', 'none'),
                   ('IFLA_INFO_KIND', 'asciiz'),
                   ('IFLA_INFO_DATA', 'info_data'),
                   ('IFLA_INFO_XSTATS', 'hex'),
                   ('IFLA_INFO_SLAVE_KIND', 'asciiz'),
                   ('IFLA_INFO_SLAVE_DATA', 'info_data'))

        def info_data(self, *argv, **kwarg):
            '''
            The function returns appropriate IFLA_INFO_DATA
            type according to IFLA_INFO_KIND info. Return
            'hex' type for all unknown kind's and when the
            kind is not known.
            '''
            kind = self.get_attr('IFLA_INFO_KIND')
            if kind == 'vlan':
                return self.vlan_data
            elif kind == 'bond':
                return self.bond_data
            elif kind == 'veth':
                return self.veth_data
            elif kind == 'tuntap':
                return self.tuntap_data
            elif kind == 'bridge':
                return self.bridge_data
            return self.hex

        class tuntap_data(nla):
            '''
            Fake data type
            '''
            prefix = 'IFTUN_'

            nla_map = (('IFTUN_UNSPEC', 'none'),
                       ('IFTUN_MODE', 'asciiz'),
                       ('IFTUN_UID', 'uint32'),
                       ('IFTUN_GID', 'uint32'),
                       ('IFTUN_IFR', 'flags'))

            class flags(nla):
                fields = (('no_pi', 'B'),
                          ('one_queue', 'B'),
                          ('vnet_hdr', 'B'),
                          ('tun_excl', 'B'),
                          ('multi_queue', 'B'),
                          ('persist', 'B'),
                          ('nofilter', 'B'))

        class veth_data(nla):
            nla_map = (('VETH_INFO_UNSPEC', 'none'),
                       ('VETH_INFO_PEER', 'info_peer'))

            def info_peer(self, *argv, **kwarg):
                return ifinfveth

        class vlan_data(nla):
            nla_map = (('IFLA_VLAN_UNSPEC', 'none'),
                       ('IFLA_VLAN_ID', 'uint16'),
                       ('IFLA_VLAN_FLAGS', 'vlan_flags'),
                       ('IFLA_VLAN_EGRESS_QOS', 'hex'),
                       ('IFLA_VLAN_INGRESS_QOS', 'hex'))

            class vlan_flags(nla):
                fields = (('flags', 'I'),
                          ('mask', 'I'))

        class bridge_data(nla):
            prefix = 'IFLA_BRIDGE_'
            nla_map = (('IFLA_BRIDGE_STP_STATE', 'uint32'),
                       ('IFLA_BRIDGE_MAX_AGE', 'uint32'))

        class bond_data(nla):
            prefix = 'IFLA_BOND_'
            nla_map = (('IFLA_BOND_UNSPEC', 'none'),
                       ('IFLA_BOND_MODE', 'uint8'),
                       ('IFLA_BOND_ACTIVE_SLAVE', 'uint32'),
                       ('IFLA_BOND_MIIMON', 'uint32'),
                       ('IFLA_BOND_UPDELAY', 'uint32'),
                       ('IFLA_BOND_DOWNDELAY', 'uint32'),
                       ('IFLA_BOND_USE_CARRIER', 'uint8'),
                       ('IFLA_BOND_ARP_INTERVAL', 'uint32'),
                       ('IFLA_BOND_ARP_IP_TARGET', 'arp_ip_target'),
                       ('IFLA_BOND_ARP_VALIDATE', 'uint32'),
                       ('IFLA_BOND_ARP_ALL_TARGETS', 'uint32'),
                       ('IFLA_BOND_PRIMARY', 'uint32'),
                       ('IFLA_BOND_PRIMARY_RESELECT', 'uint8'),
                       ('IFLA_BOND_FAIL_OVER_MAC', 'uint8'),
                       ('IFLA_BOND_XMIT_HASH_POLICY', 'uint8'),
                       ('IFLA_BOND_RESEND_IGMP', 'uint32'),
                       ('IFLA_BOND_NUM_PEER_NOTIF', 'uint8'),
                       ('IFLA_BOND_ALL_SLAVES_ACTIVE', 'uint8'),
                       ('IFLA_BOND_MIN_LINKS', 'uint32'),
                       ('IFLA_BOND_LP_INTERVAL', 'uint32'),
                       ('IFLA_BOND_PACKETS_PER_SLAVE', 'uint32'),
                       ('IFLA_BOND_AD_LACP_RATE', 'uint8'),
                       ('IFLA_BOND_AD_SELECT', 'uint8'),
                       ('IFLA_BOND_AD_INFO', 'ad_info'))

            class ad_info(nla):
                nla_map = (('IFLA_BOND_AD_INFO_UNSPEC', 'none'),
                           ('IFLA_BOND_AD_INFO_AGGREGATOR', 'uint16'),
                           ('IFLA_BOND_AD_INFO_NUM_PORTS', 'uint16'),
                           ('IFLA_BOND_AD_INFO_ACTOR_KEY', 'uint16'),
                           ('IFLA_BOND_AD_INFO_PARTNER_KEY', 'uint16'),
                           ('IFLA_BOND_AD_INFO_PARTNER_MAC', 'l2addr'))

            class arp_ip_target(nla):
                fields = (('targets', '16I'), )

    class af_spec(nla):
        nla_map = (('AF_UNSPEC', 'none'),
                   ('AF_UNIX', 'hex'),
                   ('AF_INET', 'inet'),
                   ('AF_AX25', 'hex'),
                   ('AF_IPX', 'hex'),
                   ('AF_APPLETALK', 'hex'),
                   ('AF_NETROM', 'hex'),
                   ('AF_BRIDGE', 'hex'),
                   ('AF_ATMPVC', 'hex'),
                   ('AF_X25', 'hex'),
                   ('AF_INET6', 'inet6'))

        class inet(nla):
            #  ./include/linux/inetdevice.h: struct ipv4_devconf
            field_names = ('sysctl',
                           'forwarding',
                           'mc_forwarding',
                           'proxy_arp',
                           'accept_redirects',
                           'secure_redirects',
                           'send_redirects',
                           'shared_media',
                           'rp_filter',
                           'accept_source_route',
                           'bootp_relay',
                           'log_martians',
                           'tag',
                           'arp_filter',
                           'medium_id',
                           'disable_xfrm',
                           'disable_policy',
                           'force_igmp_version',
                           'arp_announce',
                           'arp_ignore',
                           'promote_secondaries',
                           'arp_accept',
                           'arp_notify',
                           'accept_local',
                           'src_valid_mark',
                           'proxy_arp_pvlan',
                           'route_localnet')
            fields = [(i, 'I') for i in field_names]

        class inet6(nla):
            nla_map = (('IFLA_INET6_UNSPEC', 'none'),
                       ('IFLA_INET6_FLAGS', 'uint32'),
                       ('IFLA_INET6_CONF', 'ipv6_devconf'),
                       ('IFLA_INET6_STATS', 'ipv6_stats'),
                       ('IFLA_INET6_MCAST', 'hex'),
                       ('IFLA_INET6_CACHEINFO', 'ipv6_cache_info'),
                       ('IFLA_INET6_ICMP6STATS', 'icmp6_stats'),
                       ('IFLA_INET6_TOKEN', 'ip6addr'),
                       ('IFLA_INET6_ADDR_GEN_MODE', 'uint8'))

            class ipv6_devconf(nla):
                # ./include/uapi/linux/ipv6.h
                # DEVCONF_
                field_names = ('forwarding',
                               'hop_limit',
                               'mtu',
                               'accept_ra',
                               'accept_redirects',
                               'autoconf',
                               'dad_transmits',
                               'router_solicitations',
                               'router_solicitation_interval',
                               'router_solicitation_delay',
                               'use_tempaddr',
                               'temp_valid_lft',
                               'temp_prefered_lft',
                               'regen_max_retry',
                               'max_desync_factor',
                               'max_addresses',
                               'force_mld_version',
                               'accept_ra_defrtr',
                               'accept_ra_pinfo',
                               'accept_ra_rtr_pref',
                               'router_probe_interval',
                               'accept_ra_rt_info_max_plen',
                               'proxy_ndp',
                               'optimistic_dad',
                               'accept_source_route',
                               'mc_forwarding',
                               'disable_ipv6',
                               'accept_dad',
                               'force_tllao',
                               'ndisc_notify')
                fields = [(i, 'I') for i in field_names]

            class ipv6_cache_info(nla):
                # ./include/uapi/linux/if_link.h: struct ifla_cacheinfo
                fields = (('max_reasm_len', 'I'),
                          ('tstamp', 'I'),
                          ('reachable_time', 'I'),
                          ('retrans_time', 'I'))

            class ipv6_stats(nla):
                field_names = ('inoctets',
                               'fragcreates',
                               'indiscards',
                               'num',
                               'outoctets',
                               'outnoroutes',
                               'inbcastoctets',
                               'outforwdatagrams',
                               'outpkts',
                               'reasmtimeout',
                               'inhdrerrors',
                               'reasmreqds',
                               'fragfails',
                               'outmcastpkts',
                               'inaddrerrors',
                               'inmcastpkts',
                               'reasmfails',
                               'outdiscards',
                               'outbcastoctets',
                               'inmcastoctets',
                               'inpkts',
                               'fragoks',
                               'intoobigerrors',
                               'inunknownprotos',
                               'intruncatedpkts',
                               'outbcastpkts',
                               'reasmoks',
                               'inbcastpkts',
                               'innoroutes',
                               'indelivers',
                               'outmcastoctets')
                fields = [(i, 'I') for i in field_names]

            class icmp6_stats(nla):
                fields = (('num', 'Q'),
                          ('inerrors', 'Q'),
                          ('outmsgs', 'Q'),
                          ('outerrors', 'Q'),
                          ('inmsgs', 'Q'))


class ifinfmsg(ifinfbase, nlmsg):
    pass


class ifinfveth(ifinfbase, nla):
    pass


def proxy_linkinfo(data, nl):
    offset = 0
    inbox = []
    while offset < len(data):
        msg = ifinfmsg(data[offset:])
        msg.decode()
        inbox.append(msg)
        offset += msg['header']['length']

    data = b''
    for msg in inbox:
        kind = None
        ifname = msg.get_attr('IFLA_IFNAME')

        # fix master
        if ANCIENT:
            master = compat_get_master(ifname)
            if master is not None:
                msg['attrs'].append(['IFLA_MASTER', master])

        # fix linkinfo & kind
        li = msg.get_attr('IFLA_LINKINFO')
        if li is not None:
            kind = li.get_attr('IFLA_INFO_KIND')
            if kind is None:
                kind = get_interface_type(ifname)
                li['attrs'].append(['IFLA_INFO_KIND', kind])
        else:
            kind = get_interface_type(ifname)
            msg['attrs'].append(['IFLA_LINKINFO',
                                 {'attrs': [['IFLA_INFO_KIND', kind]]}])

        li = msg.get_attr('IFLA_LINKINFO')
        # fetch specific interface data
        if (kind in ('bridge', 'bond')) and \
                [x for x in li['attrs'] if x[0] == 'IFLA_INFO_DATA']:
            if kind == 'bridge':
                t = '/sys/class/net/%s/bridge/%s'
                ifdata = ifinfmsg.ifinfo.bridge_data
            elif kind == 'bond':
                t = '/sys/class/net/%s/bonding/%s'
                ifdata = ifinfmsg.ifinfo.bond_data

            commands = []
            for cmd, _ in ifdata.nla_map:
                try:
                    with open(t % (ifname, ifdata.nla2name(cmd)), 'r') as f:
                        value = f.read()
                    if cmd == 'IFLA_BOND_MODE':
                        value = value.split()[1]
                    commands.append([cmd, int(value)])
                except:
                    pass
            if commands:
                li['attrs'].append(['IFLA_INFO_DATA', {'attrs': commands}])

        msg.reset()
        msg.encode()
        data += msg.buf.getvalue()

    return {'verdict': 'forward',
            'data': data}


def proxy_setlink(data, nl):

    msg = ifinfmsg(data)
    msg.decode()

    kind = None
    infodata = None

    ifname = msg.get_attr('IFLA_IFNAME')
    linkinfo = msg.get_attr('IFLA_LINKINFO')
    if linkinfo:
        kind = linkinfo.get_attr('IFLA_INFO_KIND')
        infodata = linkinfo.get_attr('IFLA_INFO_DATA')

    if kind in ('bond', 'bridge'):
        code = 0
        #
        if kind == 'bond':
            func = compat_set_bond
        elif kind == 'bridge':
            func = compat_set_bridge
        #
        for (cmd, value) in infodata.get('attrs', []):
            cmd = infodata.nla2name(cmd)
            code = func(ifname, cmd, value) or code
        #
        if code:
            err = OSError()
            err.errno = code
            raise err

    # is it a port setup?
    master = msg.get_attr('IFLA_MASTER')
    if ANCIENT and master is not None:
        def name_by_id(index):
            return nl.get_links(index)[0].get_attr('IFLA_IFNAME')

        ifname = name_by_id(msg['index'])
        if master == 0:
            # port delete
            # 1. get the current master
            m = name_by_id(compat_get_master(ifname))
            # 2. get the type of the master
            kind = compat_get_type(m)
            # 3. delete the port
            if kind == 'bridge':
                compat_del_bridge_port(m, ifname)
            elif kind == 'bond':
                compat_del_bond_port(m, ifname)
        else:
            # port add
            # 1. get the name of the master
            m = name_by_id(master)
            # 2. get the type of the master
            kind = compat_get_type(m)
            # 3. add the port
            if kind == 'bridge':
                compat_add_bridge_port(m, ifname)
            elif kind == 'bond':
                compat_add_bond_port(m, ifname)
    else:
        return {'verdict': 'forward',
                'data': data}


def proxy_dellink(data, nl):
    msg = ifinfmsg(data)
    msg.decode()

    # get full interface description
    msg = nl.get_links(msg['index'])[0]
    # get the interface kind
    kind = None
    li = msg.get_attr('IFLA_LINKINFO')
    if li is not None:
        kind = li.get_attr('IFLA_INFO_KIND')

    if kind in ('ovs-bridge', 'openvswitch'):
        return manage_ovs('remove', msg)

    if ANCIENT and kind in ('bridge', 'bond'):
        # route the request
        if kind == 'bridge':
            compat_del_bridge(msg.get_attr('IFLA_IFNAME'))
        elif kind == 'bond':
            compat_del_bond(msg.get_attr('IFLA_IFNAME'))
        # while RTM_NEWLINK is not intercepted -- sleep
        time.sleep(_ANCIENT_BARRIER)
        return

    return {'verdict': 'forward',
            'data': data}


def proxy_newlink(data, nl):
    msg = ifinfmsg(data)
    msg.decode()
    kind = None

    # get the interface kind
    linkinfo = msg.get_attr('IFLA_LINKINFO')
    if linkinfo is not None:
        kind = [x[1] for x in linkinfo['attrs']
                if x[0] == 'IFLA_INFO_KIND']
        if kind:
            kind = kind[0]

    if kind == 'tuntap':
        return manage_tuntap('create', msg)
    elif kind in ('ovs-bridge', 'openvswitch'):
        return manage_ovs('create', msg)

    if ANCIENT and kind in ('bridge', 'bond'):
        # route the request
        if kind == 'bridge':
            compat_create_bridge(msg.get_attr('IFLA_IFNAME'))
        elif kind == 'bond':
            compat_create_bond(msg.get_attr('IFLA_IFNAME'))
        # while RTM_NEWLINK is not intercepted -- sleep
        time.sleep(_ANCIENT_BARRIER)
        return

    return {'verdict': 'forward',
            'data': data}


def manage_ovs(event, msg):
    linkinfo = msg.get_attr('IFLA_LINKINFO')
    ifname = msg.get_attr('IFLA_IFNAME')
    kind = linkinfo.get_attr('IFLA_INFO_KIND')

    # operations map
    op_map = {'create': {'ovs-bridge': 'add-br',
                         'openvswitch': 'add-br'},
              'remove': {'ovs-bridge': 'del-br',
                         'openvswitch': 'del-br'}}
    op = op_map[event][kind]

    # make a call
    with open(os.devnull, 'w') as fnull:
        subprocess.check_call(['ovs-vsctl', op, ifname],
                              stdout=fnull,
                              stderr=fnull)


def manage_tuntap(event, msg):

    if TUNSETIFF is None:
        raise Exception('unsupported arch')

    if event != 'create':
        raise Exception('unsupported event')

    ifru_flags = 0
    linkinfo = msg.get_attr('IFLA_LINKINFO')
    infodata = linkinfo.get_attr('IFLA_INFO_DATA')

    flags = infodata.get_attr('IFTUN_IFR', None)
    if infodata.get_attr('IFTUN_MODE') == 'tun':
        ifru_flags |= IFT_TUN
    elif infodata.get_attr('IFTUN_MODE') == 'tap':
        ifru_flags |= IFT_TAP
    else:
        raise ValueError('invalid mode')
    if flags is not None:
        if flags['no_pi']:
            ifru_flags |= IFT_NO_PI
        if flags['one_queue']:
            ifru_flags |= IFT_ONE_QUEUE
        if flags['vnet_hdr']:
            ifru_flags |= IFT_VNET_HDR
        if flags['multi_queue']:
            ifru_flags |= IFT_MULTI_QUEUE
    ifr = msg.get_attr('IFLA_IFNAME')
    if len(ifr) > IFNAMSIZ:
        raise ValueError('ifname too long')
    ifr += (IFNAMSIZ - len(ifr)) * '\0'
    ifr = ifr.encode('ascii')
    ifr += struct.pack('H', ifru_flags)

    user = infodata.get_attr('IFTUN_UID')
    group = infodata.get_attr('IFTUN_GID')
    #
    fd = os.open(TUNDEV, os.O_RDWR)
    try:
        ioctl(fd, TUNSETIFF, ifr)
        if user is not None:
            ioctl(fd, TUNSETOWNER, user)
        if group is not None:
            ioctl(fd, TUNSETGROUP, group)
        ioctl(fd, TUNSETPERSIST, 1)
    except Exception:
        raise
    finally:
        os.close(fd)


def compat_create_bridge(name):
    with open(os.devnull, 'w') as fnull:
        subprocess.check_call(['brctl', 'addbr', name],
                              stdout=fnull,
                              stderr=fnull)


def compat_create_bond(name):
    with open(_BONDING_MASTERS, 'w') as f:
        f.write('+%s' % (name))


def compat_get_type(name):
    ##
    # is it bridge?
    try:
        with open('/sys/class/net/%s/bridge/stp_state' % name, 'r'):
            return 'bridge'
    except IOError:
        pass
    ##
    # is it bond?
    try:
        with open('/sys/class/net/%s/bonding/mode' % name, 'r'):
            return 'bond'
    except IOError:
        pass
    ##
    # don't care
    return 'unknown'


def compat_set_bond(name, cmd, value):
    # FIXME: join with bridge
    # FIXME: use internal IO, not bash
    t = 'echo %s >/sys/class/net/%s/bonding/%s'
    with open(os.devnull, 'w') as fnull:
        return subprocess.call(['bash', '-c', t % (value, name, cmd)],
                               stdout=fnull,
                               stderr=fnull)


def compat_set_bridge(name, cmd, value):
    t = 'echo %s >/sys/class/net/%s/bridge/%s'
    with open(os.devnull, 'w') as fnull:
        return subprocess.call(['bash', '-c', t % (value, name, cmd)],
                               stdout=fnull,
                               stderr=fnull)


def compat_del_bridge(name):
    with open(os.devnull, 'w') as fnull:
        subprocess.check_call(['ip', 'link', 'set',
                               'dev', name, 'down'])
        subprocess.check_call(['brctl', 'delbr', name],
                              stdout=fnull,
                              stderr=fnull)


def compat_del_bond(name):
    subprocess.check_call(['ip', 'link', 'set',
                           'dev', name, 'down'])
    with open(_BONDING_MASTERS, 'w') as f:
        f.write('-%s' % (name))


def compat_add_bridge_port(master, port):
    with open(os.devnull, 'w') as fnull:
        subprocess.check_call(['brctl', 'addif', master, port],
                              stdout=fnull,
                              stderr=fnull)


def compat_del_bridge_port(master, port):
    with open(os.devnull, 'w') as fnull:
        subprocess.check_call(['brctl', 'delif', master, port],
                              stdout=fnull,
                              stderr=fnull)


def compat_add_bond_port(master, port):
    with open(_BONDING_SLAVES % (master), 'w') as f:
        f.write('+%s' % (port))


def compat_del_bond_port(master, port):
    with open(_BONDING_SLAVES % (master), 'w') as f:
        f.write('-%s' % (port))


def compat_get_master(name):
    f = None

    for i in (_BRIDGE_MASTER, _BONDING_MASTER):
        try:
            f = open(i % (name))
            break
        except IOError:
            pass

    if f is not None:
        master = int(f.read())
        f.close()
        return master


def get_interface_type(name):
    '''
    Utility function to get interface type.

    Unfortunately, we can not rely on RTNL or even ioctl().
    RHEL doesn't support interface type in RTNL and doesn't
    provide extended (private) interface flags via ioctl().

    Args:
        * name (str): interface name

    Returns:
        * False -- sysfs info unavailable
        * None -- type not known
        * str -- interface type:
            * 'bond'
            * 'bridge'
    '''
    # FIXME: support all interface types? Right now it is
    # not needed
    try:
        ifattrs = os.listdir('/sys/class/net/%s/' % (name))
    except OSError as e:
        if e.errno == 2:
            return False
        else:
            raise

    if 'bonding' in ifattrs:
        return 'bond'
    elif 'bridge' in ifattrs:
        return 'bridge'
    else:
        return None
