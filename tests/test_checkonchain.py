"""checkonchain chart parsing. No network."""
import base64
import json
import pathlib
import struct
import sys
import unittest
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import checkonchain as C  # noqa: E402

NOW = datetime(2026, 11, 7, 9, tzinfo=timezone.utc)


def page(traces):
    return '<html><script>Plotly.newPlot("id", ' + json.dumps(traces) + ', {"layout": 1}, {})</script></html>'


def typed(values):
    return {'dtype': 'f8', 'bdata': base64.b64encode(struct.pack('<%dd' % len(values), *values)).decode()}


DAYS = ['2026-11-05T00:00:00', '2026-11-06T00:00:00', '2026-11-07T00:00:00']


class ParseTests(unittest.TestCase):
    def test_typed_arrays_decode_and_nan_is_dropped(self):
        found = C.traces(page([{'name': 'A', 'x': DAYS, 'y': typed([1.5, float('nan'), 3.0])}]))
        self.assertEqual(found['A'], {'2026-11-05': 1.5, '2026-11-07': 3.0})

    def test_the_forming_utc_day_is_never_stored(self):
        spec = {'k': ('first', ('A',))}
        out = C.parse_chart(page([{'name': 'A', 'x': DAYS, 'y': [1, 2, 3]}]), spec, '2026-11-07')
        self.assertEqual(sorted(out['k']), ['2026-11-05', '2026-11-06'])

    def test_split_positive_negative_traces_are_summed(self):
        html = page([{'name': 'P', 'x': DAYS, 'y': [0, 5, 0]}, {'name': 'N', 'x': DAYS, 'y': [-4, 0, -1]}])
        out = C.parse_chart(html, {'k': ('sum', ('P', 'N'))}, '2026-11-08')
        self.assertEqual(out['k'], {'2026-11-05': -4.0, '2026-11-06': 5.0, '2026-11-07': -1.0})

    def test_ratio_and_zone_union(self):
        html = page([{'name': 'R', 'x': DAYS, 'y': [8, 9, 10]}, {'name': 'C', 'x': DAYS, 'y': [10, 0, 10]},
                     {'name': 'Z1', 'x': DAYS, 'y': [0.1, None, None]}, {'name': 'Z2', 'x': DAYS, 'y': [None, 0.2, 0.3]}])
        out = C.parse_chart(html, {'r': ('ratio', ('R', 'C')), 'z': ('any', ('Z1', 'Z2'))}, '2026-11-08')
        self.assertEqual(out['r'], {'2026-11-05': 0.8, '2026-11-07': 1.0})
        self.assertEqual(out['z'], {'2026-11-05': 0.1, '2026-11-06': 0.2, '2026-11-07': 0.3})

    def test_a_renamed_trace_fails_loudly(self):
        with self.assertRaises(KeyError):
            C.parse_chart(page([{'name': 'B', 'x': DAYS, 'y': [1, 2, 3]}]), {'k': ('first', ('A',))}, '2026-11-08')


class RefreshTests(unittest.TestCase):
    def test_failure_keeps_history_and_success_merges(self):
        store = {'series': {'cc_mvrv_z': {'2026-11-01': -0.3}}, 'fetched': {}}

        def fetch(url):
            if 'mvrv_all_zscore' in url:
                raise OSError('down')
            raise ValueError('not a chart')
        store, errors = C.refresh(store, NOW, fetch)
        self.assertEqual(store['series']['cc_mvrv_z'], {'2026-11-01': -0.3})
        self.assertEqual(len(errors), len(C.CHARTS))

    def test_recently_fetched_charts_are_skipped(self):
        path = next(iter(C.CHARTS))
        store = {'series': {}, 'fetched': {'cc:' + path: NOW.isoformat()}}
        seen = []
        C.refresh(store, NOW, lambda url: seen.append(url) or '')
        self.assertNotIn(C.chart_url(path), seen)
        self.assertEqual(len(seen), len(C.CHARTS) - 1)


if __name__ == '__main__':
    unittest.main()
