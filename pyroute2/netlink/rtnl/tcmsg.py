import struct

from pyroute2.netlink.generic import nlmsg
from pyroute2.netlink.generic import nla

LINKLAYER_UNSPEC = 0
LINKLAYER_ETHERNET = 1
LINKLAYER_ATM = 2

ATM_CELL_SIZE = 53
ATM_CELL_PAYLOAD = 48

TIME_UNITS_PER_SEC = 1000000

_psched = open('/proc/net/psched', 'r')
[_t2us,
 _us2t,
 _clock_res,
 _wee] = [int(i, 16) for i in _psched.read().split()]
_clock_factor = float(_clock_res) / TIME_UNITS_PER_SEC
_tick_in_usec = float(_t2us) / _us2t * _clock_factor


def _time2tick(t):
    # The current code is ported from tc utility
    return t * _tick_in_usec


def _calc_xmittime(rate, size):
    # The current code is ported from tc utility
    return _time2tick(TIME_UNITS_PER_SEC * (float(size) / rate))


def get_tbf_parameters(kwarg):
    # rate and burst are required
    rate = kwarg['rate']
    burst = kwarg['burst']

    # if peak, mtu is required
    peak = kwarg.get('peak', 0)
    mtu = kwarg.get('mtu', 0)
    if peak:
        assert mtu

    # limit OR latency is required
    limit = kwarg.get('limit', None)
    latency = kwarg.get('latency', None)
    assert limit or latency

    # calculate limit from latency
    if limit is None:
        rate_limit = rate * float(latency) /\
            TIME_UNITS_PER_SEC + burst
        if peak:
            peak_limit = peak * float(latency) /\
                TIME_UNITS_PER_SEC + mtu
            if rate_limit > peak_limit:
                rate_limit = peak_limit
        limit = rate_limit

    # fill parameters
    return [['TCA_TBF_PARMS', {'rate': rate,
                               'mtu': mtu,
                               'buffer': _calc_xmittime(rate, burst),
                               'limit': limit}],
            ['TCA_TBF_RTAB', True]]


def get_htb_parameters(kwarg):
    rate2quantum = kwarg.get('r2q', 0xa)
    version = kwarg.get('version', 3)
    defcls = kwarg.get('default', 0x10)
    ret = [['TCA_HTB_INIT', {'debug': 0,
                             'defcls': defcls,
                             'direct_pkts': 0,
                             'rate2quantum': rate2quantum,
                             'version': version}]]
    return ret


class nla_plus_rtab(nla):
    class parms(nla):
        def adjust_size(self, size, mpu, linklayer):
            # The current code is ported from tc utility
            if size < mpu:
                size = mpu

            if linklayer == LINKLAYER_ATM:
                cells = size / ATM_CELL_PAYLOAD
                if size % ATM_CELL_PAYLOAD > 0:
                    cells += 1
                size = cells * ATM_CELL_SIZE

            return size

        def calc_rtab(self, kind):
            # The current code is ported from tc utility
            rtab = []
            mtu = self.get('mtu', 0) or 1600
            cell_log = self['%s_cell_log' % (kind)]
            mpu = self['%s_mpu' % (kind)]
            rate = self['rate']

            # calculate cell_log
            if cell_log == 0:
                while (mtu >> cell_log) > 255:
                    cell_log += 1

            # fill up the table
            for i in range(256):
                size = self.adjust_size((i + 1) << cell_log,
                                        mpu,
                                        LINKLAYER_ETHERNET)
                rtab.append(_calc_xmittime(rate, size))

            self['%s_cell_align' % (kind)] = -1
            self['%s_cell_log' % (kind)] = cell_log
            return rtab

        def encode(self):
            self.rtab = None
            self.ptab = None
            if self['rate']:
                self.rtab = self.calc_rtab('rate')
            if self['peak']:
                self.ptab = self.calc_ptab('peak')
            nla.encode(self)

    class rtab(nla):
        fmt = 's'

        def encode(self):
            parms = self.parent.get_attr('TCA_TBF_PARMS') or \
                self.parent.get_attr('TCA_HTB_PARMS')
            if parms:
                self.value = getattr(parms[0], self.__class__.__name__)
                self['value'] = struct.pack('I' * 256, *self.value)
            nla.encode(self)

        def decode(self):
            nla.decode(self)
            parms = self.parent.get_attr('TCA_TBF_PARMS') or \
                self.parent.get_attr('TCA_HTB_PARMS')
            if parms:
                rtab = struct.unpack('I' * (len(self['value']) / 4),
                                     self['value'])
                self.value = rtab
                setattr(parms[0], self.__class__.__name__, rtab)

    class ptab(rtab):
        pass

    class ctab(rtab):
        pass


class nla_plus_police(nla):
    class police(nla):
        nla_map = (('TCA_POLICE_UNSPEC', 'none'),
                   ('TCA_POLICE_TBF', 'police_tbf'),
                   ('TCA_POLICE_RATE', 'hex'),
                   ('TCA_POLICE_PEAKRATE', 'hex'),
                   ('TCA_POLICE_AVRATE', 'hex'),
                   ('TCA_POLICE_RESULT', 'hex'))

        class police_tbf(nla):
            t_fields = (('index', 'I'),
                        ('action', 'i'),
                        ('limit', 'I'),
                        ('burst', 'I'),
                        ('mtu', 'I'),
                        ('rate_cell_log', 'B'),
                        ('rate___reserved', 'B'),
                        ('rate_overhead', 'H'),
                        ('rate_cell_align', 'h'),
                        ('rate_mpu', 'H'),
                        ('rate', 'I'),
                        ('peak_cell_log', 'B'),
                        ('peak___reserved', 'B'),
                        ('peak_overhead', 'H'),
                        ('peak_cell_align', 'h'),
                        ('peak_mpu', 'H'),
                        ('peak', 'I'),
                        ('refcnt', 'i'),
                        ('bindcnt', 'i'),
                        ('capab', 'I'))


class tcmsg(nlmsg):
    t_fields = (('family', 'B'),
                ('pad1', 'B'),
                ('pad2', 'H'),
                ('index', 'i'),
                ('handle', 'I'),
                ('parent', 'I'),
                ('info', 'I'))

    nla_map = (('TCA_UNSPEC', 'none'),
               ('TCA_KIND', 'asciiz'),
               ('TCA_OPTIONS', 'get_options'),
               ('TCA_STATS', 'stats'),
               ('TCA_XSTATS', 'get_xstats'),
               ('TCA_RATE', 'hex'),
               ('TCA_FCNT', 'hex'),
               ('TCA_STATS2', 'stats2'),
               ('TCA_STAB', 'hex'))

    class stats(nla):
        t_fields = (('bytes', 'Q'),
                    ('packets', 'I'),
                    ('drop', 'I'),
                    ('overlimits', 'I'),
                    ('bps', 'I'),
                    ('pps', 'I'),
                    ('qlen', 'I'),
                    ('backlog', 'I'))

    class stats2(nla):
        nla_map = (('TCA_STATS_UNSPEC', 'none'),
                   ('TCA_STATS_BASIC', 'basic'),
                   ('TCA_STATS_RATE_EST', 'rate_est'),
                   ('TCA_STATS_QUEUE', 'queue'),
                   ('TCA_STATS_APP', 'hex'))

        class basic(nla):
            t_fields = (('bytes', 'Q'),
                        ('packets', 'Q'))

        class rate_est(nla):
            t_fields = (('bps', 'I'),
                        ('pps', 'I'))

        class queue(nla):
            t_fields = (('qlen', 'I'),
                        ('backlog', 'I'),
                        ('drops', 'I'),
                        ('requeues', 'I'),
                        ('overlimits', 'I'))

    def get_xstats(self, *argv, **kwarg):
        kind = self.get_attr('TCA_KIND')
        if kind:
            if kind[0] == 'htb':
                return self.xstats_htb
        return self.hex

    class xstats_htb(nla):
        t_fields = (('lends', 'I'),
                    ('borrows', 'I'),
                    ('giants', 'I'),
                    ('tokens', 'I'),
                    ('ctokens', 'I'))

    def get_options(self, *argv, **kwarg):
        kind = self.get_attr('TCA_KIND')
        if kind:
            if kind[0] == 'ingress':
                return self.options_ingress
            elif kind[0] == 'pfifo_fast':
                return self.options_pfifo_fast
            elif kind[0] == 'tbf':
                return self.options_tbf
            elif kind[0] == 'sfq':
                if kwarg.get('length', 0) >= \
                        struct.calcsize(self.options_sfq_v1.fmt):
                    return self.options_sfq_v1
                else:
                    return self.options_sfq_v0
            elif kind[0] == 'htb':
                return self.options_htb
            elif kind[0] == 'u32':
                return self.options_u32
            elif kind[0] == 'fw':
                return self.options_fw
        return self.hex

    class options_ingress(nla):
        fmt = 'I'

    class options_htb(nla_plus_rtab):
        nla_map = (('TCA_HTB_UNSPEC', 'none'),
                   ('TCA_HTB_PARMS', 'htb_parms'),
                   ('TCA_HTB_INIT', 'htb_glob'),
                   ('TCA_HTB_CTAB', 'ctab'),
                   ('TCA_HTB_RTAB', 'rtab'))

        class htb_glob(nla):
            t_fields = (('version', 'I'),
                        ('rate2quantum', 'I'),
                        ('defcls', 'I'),
                        ('debug', 'I'),
                        ('direct_pkts', 'I'))

        class htb_parms(nla_plus_rtab.parms):
            t_fields = (('rate_cell_log', 'B'),
                        ('rate___reserved', 'B'),
                        ('rate_overhead', 'H'),
                        ('rate_cell_align', 'h'),
                        ('rate_mpu', 'H'),
                        ('rate', 'I'),
                        ('ceil_cell_log', 'B'),
                        ('ceil___reserved', 'B'),
                        ('ceil_overhead', 'H'),
                        ('ceil_cell_align', 'h'),
                        ('ceil_mpu', 'H'),
                        ('ceil', 'I'),
                        ('buffer', 'I'),
                        ('cbuffer', 'I'),
                        ('quantum', 'I'),
                        ('level', 'I'),
                        ('prio', 'I'))

    class options_fw(nla_plus_police):
        nla_map = (('TCA_FW_UNSPEC', 'none'),
                   ('TCA_FW_CLASSID', 'uint32'),
                   ('TCA_FW_POLICE', 'police'),
                   ('TCA_FW_INDEV', 'hex'),
                   ('TCA_FW_ACT', 'hex'),
                   ('TCA_FW_MASK', 'hex'))

    class options_u32(nla_plus_police):
        nla_map = (('TCA_U32_UNSPEC', 'none'),
                   ('TCA_U32_CLASSID', 'uint32'),
                   ('TCA_U32_HASH', 'uint32'),
                   ('TCA_U32_LINK', 'hex'),
                   ('TCA_U32_DIVISOR', 'uint32'),
                   ('TCA_U32_SEL', 'u32_sel'),
                   ('TCA_U32_POLICE', 'police'),
                   ('TCA_U32_ACT', 'hex'),
                   ('TCA_U32_INDEV', 'hex'),
                   ('TCA_U32_PCNT', 'u32_pcnt'),
                   ('TCA_U32_MARK', 'u32_mark'))

        class u32_sel(nla):
            t_fields = (('flags', 'B'),
                        ('offshift', 'B'),
                        ('nkeys', 'B'),
                        ('offmask', 'H'),  # FIXME: be16
                        ('off', 'H'),
                        ('offoff', 'h'),
                        ('hoff', 'h'),
                        ('hmask', 'I'),  # FIXME: be32
                        ('key_mask', 'I'),  # FIXME: be32
                        ('key_val', 'I'),  # FIXME: be32
                        ('key_off', 'i'),
                        ('key_offmask', 'i'))

        class u32_mark(nla):
            t_fields = (('val', 'I'),
                        ('mask', 'I'),
                        ('success', 'I'))

        class u32_pcnt(nla):
            t_fields = (('rcnt', 'Q'),
                        ('rhit', 'Q'),
                        ('kcnts', 'Q'))

    class options_pfifo_fast(nla):
        fmt = 'i' + 'B' * 16
        fields = tuple(['bands'] + ['mark_%02i' % (i) for i in
                                    range(1, 17)])

    class options_tbf(nla_plus_rtab):
        nla_map = (('TCA_TBF_UNSPEC', 'none'),
                   ('TCA_TBF_PARMS', 'tbf_parms'),
                   ('TCA_TBF_RTAB', 'rtab'),
                   ('TCA_TBF_PTAB', 'ptab'))

        class tbf_parms(nla_plus_rtab.parms):
            t_fields = (('rate_cell_log', 'B'),
                        ('rate___reserved', 'B'),
                        ('rate_overhead', 'H'),
                        ('rate_cell_align', 'h'),
                        ('rate_mpu', 'H'),
                        ('rate', 'I'),
                        ('peak_cell_log', 'B'),
                        ('peak___reserved', 'B'),
                        ('peak_overhead', 'H'),
                        ('peak_cell_align', 'h'),
                        ('peak_mpu', 'H'),
                        ('peak', 'I'),
                        ('limit', 'I'),
                        ('buffer', 'I'),
                        ('mtu', 'I'))

    class options_sfq_v0(nla):
        t_fields = (('quantum', 'I'),
                    ('perturb_period', 'i'),
                    ('limit', 'I'),
                    ('divisor', 'I'),
                    ('flows', 'I'))

    class options_sfq_v1(nla):
        t_fields = (('quantum', 'I'),
                    ('perturb_period', 'i'),
                    ('limit_v0', 'I'),
                    ('divisor', 'I'),
                    ('flows', 'I'),
                    ('depth', 'I'),
                    ('headdrop', 'I'),
                    ('limit_v1', 'I'),
                    ('qth_min', 'I'),
                    ('qth_max', 'I'),
                    ('Wlog', 'B'),
                    ('Plog', 'B'),
                    ('Scell_log', 'B'),
                    ('flags', 'B'),
                    ('max_P', 'I'),
                    ('prob_drop', 'I'),
                    ('forced_drop', 'I'),
                    ('prob_mark', 'I'),
                    ('forced_mark', 'I'),
                    ('prob_mark_head', 'I'),
                    ('forced_mark_head', 'I'))